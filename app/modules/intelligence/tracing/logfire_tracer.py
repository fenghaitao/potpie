"""Logfire Tracing Integration for LLM Monitoring"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import logfire
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry import trace as otel_trace

from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Global flag to track if Logfire is initialized
_LOGFIRE_INITIALIZED = False

# Directory where per-conversation trace files are written
TRACES_DIR = Path(".traces")

# OTEL span attribute for agent id (used to build .traces/<agent_id>/... paths)
POTPIE_AGENT_ID_ATTR = "potpie.agent_id"


def _trace_path_segment(value: Optional[str], default: str = "unknown") -> str:
    """Single path segment under TRACES_DIR; disallow empty or path-like values."""
    s = (str(value).strip() if value is not None else "") or default
    return s.replace("/", "_").replace("\\", "_")


class ConversationFileExporter(SpanExporter):
    """
    OTEL SpanExporter that writes spans as JSONL to
    .traces/<agent_id>/<conversation_id>.jsonl.

    Resolves conversation_id and potpie.agent_id from span attributes, then falls
    back to trace-id registries populated when root spans are opened.
    Missing components use the path segment "unknown".
    """

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            TRACES_DIR.mkdir(exist_ok=True)
            for span in spans:
                attrs = span.attributes or {}
                conversation_id = attrs.get("conversation_id")
                agent_id = attrs.get(POTPIE_AGENT_ID_ATTR)
                trace_id_hex = (
                    format(span.context.trace_id, "032x") if span.context else None
                )
                if not conversation_id and trace_id_hex:
                    conversation_id = _trace_id_to_conversation.get(trace_id_hex)
                if not agent_id and trace_id_hex:
                    agent_id = _trace_id_to_agent_id.get(trace_id_hex)
                agent_seg = _trace_path_segment(agent_id)
                conv_seg = _trace_path_segment(conversation_id)
                dest_dir = TRACES_DIR / agent_seg
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f"{conv_seg}.jsonl"
                record = _span_to_dict(span)
                with open(dest, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"ConversationFileExporter failed to write span: {e}")
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


# Maps trace_id (hex) → conversation_id so child spans can be routed correctly
_trace_id_to_conversation: dict = {}

# Maps trace_id (hex) → agent_id for the same purpose
_trace_id_to_agent_id: dict = {}


def _span_to_dict(span: ReadableSpan) -> dict:
    """Serialize a ReadableSpan to a plain dict suitable for JSONL."""
    return {
        "name": span.name,
        "trace_id": format(span.context.trace_id, "032x") if span.context else None,
        "span_id": format(span.context.span_id, "016x") if span.context else None,
        "parent_span_id": (
            format(span.parent.span_id, "016x") if span.parent else None
        ),
        "start_time": span.start_time,
        "end_time": span.end_time,
        "status": span.status.status_code.name if span.status else None,
        "attributes": dict(span.attributes) if span.attributes else {},
        "events": [
            {
                "name": e.name,
                "timestamp": e.timestamp,
                "attributes": dict(e.attributes) if e.attributes else {},
            }
            for e in (span.events or [])
        ],
    }


def set_conversation_context(
    conversation_id: str, agent_id: Optional[str] = None
) -> None:
    """
    Stamp conversation_id (and optional potpie.agent_id) onto the active OTEL span.

    If there is no active span (e.g. CLI path), starts a new root span
    so the exporter has something to write to the file.
    """
    span = otel_trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("conversation_id", conversation_id)
        if agent_id:
            span.set_attribute(POTPIE_AGENT_ID_ATTR, agent_id)
        sc = span.get_span_context()
        if sc and sc.is_valid:
            trace_id_hex = format(sc.trace_id, "032x")
            _trace_id_to_conversation[trace_id_hex] = conversation_id
            if agent_id:
                _trace_id_to_agent_id[trace_id_hex] = agent_id
    else:
        # No active span (CLI / background task) — open a root span and store it
        # so child spans created by pydantic-ai/litellm are nested under it.
        # Callers are responsible for ending it; we attach it to a module-level
        # registry keyed by conversation_id.
        _start_root_span(conversation_id, agent_id=agent_id)


# Registry of open root spans for CLI / non-request contexts
_root_spans: dict = {}


def _start_root_span(
    conversation_id: str, agent_id: Optional[str] = None
) -> None:
    """Open a root logfire span for the given conversation and register it."""
    if conversation_id in _root_spans:
        return
    tracer = otel_trace.get_tracer("potpie.conversation")
    span = tracer.start_span(f"conversation:{conversation_id}")
    span.set_attribute("conversation_id", conversation_id)
    if agent_id:
        span.set_attribute(POTPIE_AGENT_ID_ATTR, agent_id)
    # Register trace_id → conversation_id / agent_id so child spans can be routed
    if span.get_span_context():
        trace_id_hex = format(span.get_span_context().trace_id, "032x")
        _trace_id_to_conversation[trace_id_hex] = conversation_id
        if agent_id:
            _trace_id_to_agent_id[trace_id_hex] = agent_id
    ctx = otel_trace.set_span_in_context(span)
    from opentelemetry.context import attach
    token = attach(ctx)
    _root_spans[conversation_id] = (span, token)


def end_conversation_span(conversation_id: str) -> None:
    """End and flush the root span for a conversation. Call after agent run completes."""
    entry = _root_spans.pop(conversation_id, None)
    if entry:
        span, token = entry
        if span.get_span_context():
            trace_id_hex = format(span.get_span_context().trace_id, "032x")
            _trace_id_to_conversation.pop(trace_id_hex, None)
            _trace_id_to_agent_id.pop(trace_id_hex, None)
        span.end()
        from opentelemetry.context import detach
        detach(token)


def initialize_logfire_tracing(
    project_name: Optional[str] = None,
    token: Optional[str] = None,
    environment: Optional[str] = None,
    send_to_logfire: bool = True,
) -> bool:
    """
    Initialize Logfire tracing for the application.

    This should be called once at application startup, ideally in main.py
    before any LLM calls are made.

    Args:
        project_name: Name of the project in Logfire UI. If None, reads from LOGFIRE_PROJECT_NAME env var
        token: Logfire API token. If None, reads from LOGFIRE_TOKEN env var
        environment: Environment identifier (e.g., "development", "production", "staging", "testing")
        send_to_logfire: Whether to send traces to Logfire cloud (default: True)

    Returns:
        bool: True if initialization successful, False otherwise

    Environment Variables:
        LOGFIRE_SEND_TO_CLOUD: Set to "false" to disable sending traces to Logfire cloud (default: "true")
        LOGFIRE_TOKEN: API token for Logfire (required for cloud tracing)
        LOGFIRE_PROJECT_NAME: Project name in Logfire UI (optional)
        ENV: Environment identifier - used as "environment" attribute in traces (default: "local")
    """
    global _LOGFIRE_INITIALIZED

    # Check if cloud sending is disabled via env var
    if os.getenv("LOGFIRE_SEND_TO_CLOUD", "true").lower() == "false":
        send_to_logfire = False

    # Check if already initialized
    if _LOGFIRE_INITIALIZED:
        logger.info("Logfire tracing already initialized")
        return True

    try:
        config_kwargs: Dict[str, Any] = {}

        token = token or os.getenv("LOGFIRE_TOKEN")
        if token:
            config_kwargs["token"] = token
            config_kwargs["send_to_logfire"] = send_to_logfire
        else:
            config_kwargs["send_to_logfire"] = False
            config_kwargs["additional_span_processors"] = [
                SimpleSpanProcessor(ConversationFileExporter())
            ]
            logger.info(
                f"No Logfire token — traces will be written to "
                f"{TRACES_DIR}/<agent_id>/<conversation_id>.jsonl"
            )

        env = environment or os.getenv("ENV", "local")
        config_kwargs["environment"] = env

        project = project_name or os.getenv("LOGFIRE_PROJECT_NAME", "potpie")
        logger.debug(
            "Initializing Logfire tracing",
            project=project,
            environment=env,
            send_to_logfire=send_to_logfire,
        )
        logfire.configure(**config_kwargs)

        logfire.instrument_pydantic_ai()
        logger.info("Instrumented Pydantic AI for Logfire tracing")

        logfire.instrument_litellm()
        logger.info("Instrumented LiteLLM for Logfire tracing")

        _LOGFIRE_INITIALIZED = True

        logger.info("Logfire tracing initialized successfully.")
        return True

    except Exception as e:
        logger.warning(
            "Failed to initialize Logfire tracing (non-fatal)",
            error=str(e),
        )
        return False


def is_logfire_enabled() -> bool:
    """Check if Logfire tracing is enabled and initialized."""
    return _LOGFIRE_INITIALIZED


def shutdown_logfire_tracing():
    """
    Shutdown Logfire tracing.

    This should be called on application shutdown to ensure all traces are sent.
    Note: Logfire handles flushing automatically, but this provides a clean shutdown.
    """
    global _LOGFIRE_INITIALIZED

    if not _LOGFIRE_INITIALIZED:
        return

    try:
        import logfire

        # Logfire handles flushing automatically
        # Force a final flush to ensure all spans are sent
        logfire.force_flush()
        logger.info("Logfire tracing shutdown successfully")

        _LOGFIRE_INITIALIZED = False

    except Exception as e:
        logger.warning("Error shutting down Logfire tracing", error=str(e))
