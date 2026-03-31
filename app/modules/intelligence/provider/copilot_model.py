"""
PydanticAI Model implementation backed by GitHub Copilot CLI SDK.

This is a drop-in replacement for LiteLLMModel / OpenAIModel that routes
all LLM calls through the locally-installed `copilot` CLI binary (github-copilot-sdk).

Architecture
------------
CopilotModel(pydantic-ai Model)
    └── CopilotClient  (one per model instance, started lazily)
        └── CopilotSession  (one per Agent.run() call, destroyed after)

The Copilot SDK is session-based, event-driven:
  - send_and_wait()  → blocks until assistant.turn_end / session.idle
  - send() + on()    → non-blocking; events arrive via callback (used for streaming)

Usage
-----
    from app.modules.intelligence.provider.copilot_model import CopilotModel

    model = CopilotModel("gpt-4o")
    async with model:
        agent = Agent(model, system_prompt="You are helpful.")
        result = await agent.run("Hello!")
"""
from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from pydantic_ai._utils import now_utc
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from app.modules.utils.logger import setup_logger

try:
    from copilot import CopilotClient, PermissionHandler
    from copilot.types import SessionConfig
    from copilot.generated.session_events import SessionEventType
except ImportError as e:
    raise ImportError(
        "Please install 'github-copilot-sdk' to use CopilotModel: "
        "uv pip install github-copilot-sdk"
    ) from e

logger = setup_logger(__name__)

__all__ = ("CopilotModel", "set_copilot_session_log")

# ---------------------------------------------------------------------------
# Session log — dumps every Copilot SDK request+response to a file.
# Call set_copilot_session_log(path) once before running the evaluator.
# ---------------------------------------------------------------------------

_session_log = None  # file handle; None means disabled


def set_copilot_session_log(path: str) -> None:
    """Open *path* (append mode) and record all Copilot SDK call I/O to it."""
    global _session_log
    _session_log = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _session_log.write(f"\n{'='*80}\n[COPILOT SESSION] {ts}\n{'='*80}\n")


def _slog(msg: str) -> None:
    if _session_log is not None:
        _session_log.write(msg + "\n")


def _slog_request(
    call_type: str,
    model_name: str,
    system_prompt: str | None,
    user_prompt: str,
    response_text: str | None = None,
    error: BaseException | None = None,
) -> None:
    """Write a structured request/response block to the session log."""
    if _session_log is None:
        return
    sep = "-" * 60
    _slog(f"\n{sep}")
    _slog(f"[{call_type}] model={model_name}")
    if system_prompt:
        _slog(f"  system_prompt: {system_prompt[:400]}")
    _slog(f"  user_prompt ({len(user_prompt)} chars): {user_prompt[:800]}")
    if error is not None:
        _slog(f"  ERROR: {type(error).__name__}: {error}")
    elif response_text is not None:
        _slog(f"  response ({len(response_text)} chars): {response_text[:800]}")
    else:
        _slog("  response: <streaming — accumulated text logged at turn end>")
    _slog(sep)


# Default timeout for a full turn (seconds)
_DEFAULT_TIMEOUT = 300.0


class CopilotModel(Model):
    """PydanticAI Model backed by the GitHub Copilot CLI SDK.

    Drop-in replacement for LiteLLMModel / OpenAIModel — existing Agent code
    works unchanged; only the model= argument changes.

    Example::

        model = CopilotModel("gpt-4.1")
        async with model:
            agent = Agent(model, system_prompt="You are helpful.")
            result = await agent.run("Explain this codebase.")
    """

    def __init__(
        self,
        model_name: str = "gpt-4.1",
        *,
        cli_path: Optional[str] = None,
        working_directory: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        available_tools: Optional[list[str]] = None,
        excluded_tools: Optional[list[str]] = None,
    ) -> None:
        """Initialise CopilotModel.

        Args:
            model_name: Copilot model name, e.g. ``'claude-sonnet-4.6'``, ``'gpt-4.1'``.
            cli_path: Absolute path to the copilot CLI binary.
                If ``None`` the binary is located via PATH using ``shutil.which``.
            working_directory: Optional working directory passed to each Copilot session.
            timeout: Seconds to wait for a complete turn before raising ``TimeoutError``.
            available_tools: Whitelist of Copilot-native tools to enable (``None`` = all).
            excluded_tools: Blacklist of Copilot-native tools to disable.
        """
        super().__init__()
        self._model_name_str = model_name
        self.cli_path = cli_path or shutil.which("copilot")
        self.working_directory = working_directory
        self.timeout = timeout
        self.available_tools = available_tools
        self.excluded_tools = excluded_tools

        # Private state — no @dataclass, so we set manually
        self._client: Optional[Any] = None
        self._client_lock = asyncio.Lock()

        if self.cli_path is None:
            logger.warning(
                "copilot CLI not found in PATH. "
                "Requests will fail until cli_path is set or copilot is installed."
            )

    # ------------------------------------------------------------------ #
    # pydantic-ai Model interface                                          #
    # ------------------------------------------------------------------ #

    @property
    def model_name(self) -> str:  # type: ignore[override]
        return self._model_name_str

    @property
    def system(self) -> str:  # type: ignore[override]
        return "copilot"

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def _ensure_client(self) -> None:
        """Start the Copilot CLI process if not already running."""
        async with self._client_lock:
            if self._client is not None:
                return
            client_opts: dict[str, Any] = {}
            if self.cli_path:
                client_opts["cli_path"] = self.cli_path
            self._client = CopilotClient(client_opts)
            await self._client.start()
            logger.debug("CopilotClient started (cli_path=%s)", self.cli_path)

    async def cleanup(self) -> None:
        """Stop the Copilot CLI process."""
        async with self._client_lock:
            if self._client is not None:
                try:
                    await self._client.stop()
                except Exception:
                    pass
                self._client = None
                logger.debug("CopilotClient stopped")

    async def __aenter__(self) -> "CopilotModel":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.cleanup()

    # ------------------------------------------------------------------ #
    # Session helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _create_session(self, system_prompt: Optional[str]) -> Any:
        """Create a fresh Copilot session for one agent turn."""
        await self._ensure_client()
        assert self._client is not None  # ensured above

        config: SessionConfig = {
            "on_permission_request": PermissionHandler.approve_all,
            "model": self._model_name_str,
        }
        if system_prompt:
            config["system_message"] = system_prompt
        if self.working_directory:
            config["working_directory"] = self.working_directory
        if self.available_tools is not None:
            config["available_tools"] = self.available_tools
        if self.excluded_tools is not None:
            config["excluded_tools"] = self.excluded_tools

        return await self._client.create_session(config)

    # ------------------------------------------------------------------ #
    # Message conversion                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _messages_to_prompt(
        messages: list[ModelMessage],
    ) -> tuple[Optional[str], str]:
        """Convert pydantic-ai messages → (system_prompt, user_prompt).

        The Copilot SDK is session-based and manages its own history, so we
        flatten the entire conversation into a single user-prompt string that
        encodes prior turns as contextual text.
        """
        system_prompt: Optional[str] = None
        parts: list[str] = []

        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, SystemPromptPart):
                        system_prompt = part.content
                    elif isinstance(part, UserPromptPart):
                        content = part.content
                        if not isinstance(content, str):
                            content = str(content)
                        parts.append(content)
                    elif isinstance(part, ToolReturnPart):
                        parts.append(
                            f"[Tool '{part.tool_name}' returned: {part.model_response_str()}]"
                        )
            elif isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        parts.append(f"[Previous assistant response: {part.content}]")
                    elif isinstance(part, ToolCallPart):
                        parts.append(
                            f"[Assistant called tool '{part.tool_name}' with args: {part.args_as_json_str()}]"
                        )

        return system_prompt, "\n".join(parts)

    @staticmethod
    def _build_schema_instruction(
        model_request_parameters: ModelRequestParameters,
    ) -> str:
        """Append a JSON-schema constraint when structured output is requested."""
        if not model_request_parameters.output_tools:
            return ""
        output_tool = model_request_parameters.output_tools[0]
        schema_json = json.dumps(output_tool.parameters_json_schema, indent=2)
        return (
            "\n\nIMPORTANT: Your response MUST be valid JSON that conforms to "
            "this schema (respond with ONLY the JSON object, no extra text):\n"
            f"```json\n{schema_json}\n```"
        )

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Try to extract a JSON object from a free-text response."""
        text = text.strip()
        # Direct JSON
        if text.startswith("{"):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                pass
        # Fenced code block (```json ... ``` or ``` ... ```)
        for fence in ("```json", "```"):
            start = text.find(fence)
            if start != -1:
                inner_start = start + len(fence)
                end = text.find("```", inner_start)
                if end != -1:
                    candidate = text[inner_start:end].strip()
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        pass
        # Brace search
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        return None

    # ------------------------------------------------------------------ #
    # pydantic-ai request (non-streaming)                                  #
    # ------------------------------------------------------------------ #

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Blocking single-turn request via send_and_wait."""
        system_prompt, user_prompt = self._messages_to_prompt(messages)

        if model_request_parameters.output_tools:
            user_prompt += self._build_schema_instruction(model_request_parameters)

        effective_timeout = self.timeout
        if model_settings and isinstance(model_settings, dict):
            effective_timeout = model_settings.get("copilot_timeout", effective_timeout)

        session = await self._create_session(system_prompt)
        event = None
        try:
            event = await session.send_and_wait(
                {"prompt": user_prompt},
                timeout=effective_timeout,
            )
        except Exception as e:
            _slog_request("request", self._model_name_str, system_prompt, user_prompt, error=e)
            raise
        finally:
            try:
                await session.destroy()
            except Exception:
                pass

        content = ""
        if event is not None and event.data is not None:
            content = event.data.content or ""

        if not content:
            logger.warning("CopilotModel.request: empty response from Copilot SDK")

        _slog_request("request", self._model_name_str, system_prompt, user_prompt, response_text=content)

        parts: list[ModelResponsePart] = []
        if model_request_parameters.output_tools and content:
            json_str = self._extract_json(content)
            if json_str:
                output_tool = model_request_parameters.output_tools[0]
                parts.append(
                    ToolCallPart(
                        tool_name=output_tool.name,
                        args=json_str,
                    )
                )
            else:
                logger.warning(
                    "CopilotModel: structured output requested but no JSON found; "
                    "falling back to TextPart"
                )
                parts.append(TextPart(content=content))
        else:
            parts.append(TextPart(content=content))

        return ModelResponse(
            parts=parts,
            usage=RequestUsage(),
            model_name=self._model_name_str,
            timestamp=now_utc(),
            provider_name="copilot",
        )

    # ------------------------------------------------------------------ #
    # pydantic-ai request_stream (streaming)                               #
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Streaming turn via the Copilot SDK event bus."""
        system_prompt, user_prompt = self._messages_to_prompt(messages)

        if model_request_parameters.output_tools:
            user_prompt += self._build_schema_instruction(model_request_parameters)

        effective_timeout = self.timeout
        if model_settings and isinstance(model_settings, dict):
            effective_timeout = model_settings.get("copilot_timeout", effective_timeout)

        session = await self._create_session(system_prompt)
        event_queue: asyncio.Queue = asyncio.Queue()

        def _on_event(event: Any) -> None:
            event_queue.put_nowait(event)

        unsubscribe = session.on(_on_event)

        async def _stream_generator() -> AsyncIterator[Any]:
            """Yield TextPart chunks from the Copilot event stream."""
            accumulated = ""
            _error_logged = False
            try:
                await session.send({"prompt": user_prompt})

                while True:
                    try:
                        event = await asyncio.wait_for(
                            event_queue.get(), timeout=effective_timeout
                        )
                    except asyncio.TimeoutError:
                        logger.warning("CopilotModel stream: timeout waiting for event")
                        break

                    if event is None:
                        break

                    etype = event.type

                    if etype == SessionEventType.ASSISTANT_STREAMING_DELTA:
                        delta = (event.data.delta_content or "") if event.data else ""
                        if delta:
                            accumulated += delta
                            yield TextPart(content=delta)

                    elif etype == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                        delta = (event.data.delta_content or "") if event.data else ""
                        if delta:
                            accumulated += delta
                            yield TextPart(content=delta)

                    elif etype == SessionEventType.ASSISTANT_MESSAGE:
                        # Non-delta full message (fallback for non-streaming models)
                        content = (event.data.content or "") if event.data else ""
                        if content and not accumulated:
                            accumulated = content
                            yield TextPart(content=content)
                        break

                    elif etype in (
                        SessionEventType.SESSION_IDLE,
                        SessionEventType.ASSISTANT_TURN_END,
                        SessionEventType.SESSION_TASK_COMPLETE,
                    ):
                        break

                    elif etype == SessionEventType.SESSION_ERROR:
                        err_msg = (
                            (event.data.message or event.data.error or "unknown")
                            if event.data
                            else "unknown"
                        )
                        err = RuntimeError(f"Copilot session error: {err_msg}")
                        _slog_request("request_stream", self._model_name_str, system_prompt, user_prompt, error=err)
                        _error_logged = True
                        raise err

            except Exception as e:
                if not _error_logged:
                    _slog_request("request_stream", self._model_name_str, system_prompt, user_prompt, error=e)
                    _error_logged = True
                raise
            finally:
                # Log the successful turn (accumulated response); skip on error (already logged above)
                if not _error_logged:
                    _slog_request("request_stream", self._model_name_str, system_prompt, user_prompt, response_text=accumulated)
                unsubscribe()
                try:
                    await session.destroy()
                except Exception:
                    pass

        yield CopilotStreamedResponse(
            model_name=self._model_name_str,
            model_request_parameters=model_request_parameters,
            stream=_stream_generator(),
        )


# ---------------------------------------------------------------------------
# StreamedResponse implementation
# ---------------------------------------------------------------------------


class CopilotStreamedResponse(StreamedResponse):
    """Streamed response adapter for CopilotModel."""

    def __init__(
        self,
        model_name: str,
        model_request_parameters: ModelRequestParameters,
        stream: AsyncIterator[Any],
    ) -> None:
        super().__init__(model_request_parameters)
        self._model_name_value = model_name
        self._stream = stream
        self._timestamp = now_utc()

    @property
    def model_name(self) -> str:  # type: ignore[override]
        return self._model_name_value

    @property
    def provider_name(self) -> str | None:
        return "copilot"

    @property
    def provider_url(self) -> str | None:
        return None

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    async def _get_event_iterator(self) -> AsyncIterator[Any]:
        async for part in self._stream:
            if isinstance(part, TextPart) and part.content:
                for event in self._parts_manager.handle_text_delta(
                    vendor_part_id=0, content=part.content
                ):
                    yield event
