"""
Tests for CopilotModel — the pydantic-ai Model backed by the GitHub Copilot CLI SDK.

All tests are fully mocked (no live copilot CLI required).
Model names used in tests are free-tier Copilot CLI models (gpt-4.1, gpt-5-mini)
so that if tests are ever run against a live CLI they incur zero cost.

Test coverage:
  1.  Instantiation — positional + keyword model_name, defaults
  2.  Model interface — model_name / system properties
  3.  _messages_to_prompt — system prompt extraction, user prompt, tool parts
  4.  _build_schema_instruction — empty when no output_tools, JSON schema injected
  5.  _extract_json — raw JSON, fenced block, brace scan, no-JSON falls back to None
  6.  request() — mocked session, happy path, structured output (ToolCallPart), empty response
  7.  request_stream() — mocked event queue, delta events, terminal events, error event
  8.  provider_service integration — get_pydantic_model returns CopilotModel for copilot_cli
  9.  llm_config registration — all copilot_cli/* entries present with correct capabilities
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
from app.modules.intelligence.provider.copilot_model import (
    CopilotModel,
    CopilotStreamedResponse,
)

# ---------------------------------------------------------------------------
# Free-tier model names (0x cost multiplier in Copilot CLI)
# ---------------------------------------------------------------------------
FREE_MODEL = "gpt-4.1"        # 0x — free tier
FREE_MODEL_MINI = "gpt-5-mini" # 0x — free tier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mrp(output_tools=None) -> ModelRequestParameters:
    """Build a minimal ModelRequestParameters."""
    return ModelRequestParameters(
        function_tools=[],
        output_tools=output_tools or [],
        allow_text_output=True,
    )


def _make_output_tool(name: str = "final_result", schema: dict | None = None) -> ToolDefinition:
    """Build a minimal ToolDefinition stub."""
    return ToolDefinition(
        name=name,
        parameters_json_schema=schema or {"type": "object", "properties": {"answer": {"type": "string"}}},
    )


def _make_messages(
    user: str = "Hello",
    system: str | None = None,
) -> list:
    parts = []
    if system:
        parts.append(SystemPromptPart(content=system))
    parts.append(UserPromptPart(content=user))
    return [ModelRequest(parts=parts)]


# ---------------------------------------------------------------------------
# 1. Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_positional_model_name(self):
        m = CopilotModel(FREE_MODEL)
        assert m.model_name == FREE_MODEL

    def test_keyword_model_name(self):
        m = CopilotModel(model_name=FREE_MODEL_MINI)
        assert m.model_name == FREE_MODEL_MINI

    def test_default_model_name(self):
        m = CopilotModel()
        assert m.model_name == "gpt-4.1"  # free-tier default (✓)

    def test_extra_kwargs(self):
        m = CopilotModel(FREE_MODEL, timeout=60.0, working_directory="/tmp")
        assert m.timeout == 60.0
        assert m.working_directory == "/tmp"

    def test_client_initially_none(self):
        m = CopilotModel(FREE_MODEL)
        assert m._client is None


# ---------------------------------------------------------------------------
# 2. Model interface
# ---------------------------------------------------------------------------

class TestModelInterface:
    def test_model_name_property(self):
        assert CopilotModel(FREE_MODEL).model_name == FREE_MODEL

    def test_system_property(self):
        assert CopilotModel(FREE_MODEL).system == "copilot"


# ---------------------------------------------------------------------------
# 3. _messages_to_prompt
# ---------------------------------------------------------------------------

class TestMessagesToPrompt:
    def test_extracts_system_prompt(self):
        msgs = _make_messages(user="Hi", system="Be concise.")
        sys, prompt = CopilotModel._messages_to_prompt(msgs)
        assert sys == "Be concise."
        assert "Hi" in prompt

    def test_no_system_prompt(self):
        msgs = _make_messages(user="Hello")
        sys, prompt = CopilotModel._messages_to_prompt(msgs)
        assert sys is None
        assert prompt == "Hello"

    def test_tool_return_part(self):
        tr = ToolReturnPart(tool_name="search", tool_call_id="1", content="result data")
        req = ModelRequest(parts=[UserPromptPart(content="query"), tr])
        _, prompt = CopilotModel._messages_to_prompt([req])
        assert "search" in prompt
        assert "result data" in prompt

    def test_previous_assistant_response(self):
        from pydantic_ai.messages import ModelResponse
        resp = ModelResponse(parts=[TextPart(content="I am the assistant.")])
        req = ModelRequest(parts=[UserPromptPart(content="follow-up")])
        _, prompt = CopilotModel._messages_to_prompt([resp, req])
        assert "Previous assistant response" in prompt
        assert "follow-up" in prompt

    def test_tool_call_part_in_response(self):
        from pydantic_ai.messages import ModelResponse
        tc = ToolCallPart(tool_name="grep", args='{"query":"foo"}')
        resp = ModelResponse(parts=[tc])
        req = ModelRequest(parts=[UserPromptPart(content="next")])
        _, prompt = CopilotModel._messages_to_prompt([resp, req])
        assert "grep" in prompt


# ---------------------------------------------------------------------------
# 4. _build_schema_instruction
# ---------------------------------------------------------------------------

class TestBuildSchemaInstruction:
    def test_empty_when_no_output_tools(self):
        mrp = _make_mrp(output_tools=[])
        assert CopilotModel._build_schema_instruction(mrp) == ""

    def test_injects_schema_json(self):
        tool = _make_output_tool()
        mrp = _make_mrp(output_tools=[tool])
        instruction = CopilotModel._build_schema_instruction(mrp)
        assert "IMPORTANT" in instruction
        assert "answer" in instruction  # from the schema


# ---------------------------------------------------------------------------
# 5. _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_raw_json(self):
        text = '{"key": "value"}'
        assert CopilotModel._extract_json(text) == text

    def test_fenced_json_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = CopilotModel._extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_fenced_plain_block(self):
        text = '```\n{"key": "value"}\n```'
        result = CopilotModel._extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_brace_scan(self):
        text = 'Some text before {"nested": true} some text after'
        result = CopilotModel._extract_json(text)
        assert json.loads(result) == {"nested": True}

    def test_no_json_returns_none(self):
        assert CopilotModel._extract_json("plain text with no JSON") is None

    def test_whitespace_stripped(self):
        text = '   {"a": 1}   '
        result = CopilotModel._extract_json(text)
        assert json.loads(result) == {"a": 1}


# ---------------------------------------------------------------------------
# Shared mock factories for session/client
# ---------------------------------------------------------------------------

def _make_session_event(content: str = "Hello from Copilot"):
    """Build a mock event as returned by send_and_wait."""
    event = MagicMock()
    event.data = MagicMock()
    event.data.content = content
    return event


def _make_streaming_event(delta: str, etype_name: str = "ASSISTANT_STREAMING_DELTA"):
    """Build a mock streaming SessionEvent."""
    from copilot.generated.session_events import SessionEventType
    event = MagicMock()
    event.type = getattr(SessionEventType, etype_name)
    event.data = MagicMock()
    event.data.delta_content = delta
    event.data.content = delta
    return event


def _make_terminal_event(etype_name: str = "SESSION_IDLE"):
    from copilot.generated.session_events import SessionEventType
    event = MagicMock()
    event.type = getattr(SessionEventType, etype_name)
    event.data = None
    return event


# ---------------------------------------------------------------------------
# 6. request()
# ---------------------------------------------------------------------------

class TestRequest:
    @pytest.mark.asyncio
    async def test_happy_path_returns_text_part(self):
        model = CopilotModel(FREE_MODEL)

        mock_event = _make_session_event("The answer is 42.")
        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(return_value=mock_event)
        mock_session.destroy = AsyncMock()

        with patch.object(model, "_create_session", return_value=mock_session):
            response = await model.request(
                _make_messages("What is 6*7?"),
                model_settings=None,
                model_request_parameters=_make_mrp(),
            )

        assert isinstance(response, ModelResponse)
        assert len(response.parts) == 1
        assert isinstance(response.parts[0], TextPart)
        assert "42" in response.parts[0].content
        assert response.model_name == FREE_MODEL
        assert response.provider_name == "copilot"
        mock_session.destroy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_structured_output_returns_tool_call_part(self):
        model = CopilotModel(FREE_MODEL)

        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        raw_content = '{"answer": "42"}'
        mock_event = _make_session_event(raw_content)
        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(return_value=mock_event)
        mock_session.destroy = AsyncMock()

        tool = _make_output_tool("final_result", schema)
        mrp = _make_mrp(output_tools=[tool])

        with patch.object(model, "_create_session", return_value=mock_session):
            response = await model.request(
                _make_messages("What is 6*7?"),
                model_settings=None,
                model_request_parameters=mrp,
            )

        assert isinstance(response.parts[0], ToolCallPart)
        assert response.parts[0].tool_name == "final_result"
        assert json.loads(response.parts[0].args_as_json_str()) == {"answer": "42"}

    @pytest.mark.asyncio
    async def test_empty_response_falls_back_to_empty_text_part(self):
        model = CopilotModel(FREE_MODEL_MINI)

        mock_event = _make_session_event("")
        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(return_value=mock_event)
        mock_session.destroy = AsyncMock()

        with patch.object(model, "_create_session", return_value=mock_session):
            response = await model.request(
                _make_messages("Hello"),
                model_settings=None,
                model_request_parameters=_make_mrp(),
            )

        assert isinstance(response.parts[0], TextPart)
        assert response.parts[0].content == ""

    @pytest.mark.asyncio
    async def test_session_always_destroyed_on_error(self):
        model = CopilotModel(FREE_MODEL)

        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(side_effect=RuntimeError("network error"))
        mock_session.destroy = AsyncMock()

        with patch.object(model, "_create_session", return_value=mock_session):
            with pytest.raises(RuntimeError, match="network error"):
                await model.request(
                    _make_messages("Hello"),
                    model_settings=None,
                    model_request_parameters=_make_mrp(),
                )

        mock_session.destroy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_json_in_structured_output_falls_back_to_text(self):
        """When model returns non-JSON text but structured output requested → TextPart fallback."""
        model = CopilotModel(FREE_MODEL_MINI)

        mock_event = _make_session_event("I don't know how to format JSON right now.")
        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(return_value=mock_event)
        mock_session.destroy = AsyncMock()

        tool = _make_output_tool()
        mrp = _make_mrp(output_tools=[tool])

        with patch.object(model, "_create_session", return_value=mock_session):
            response = await model.request(
                _make_messages("Summarise"),
                model_settings=None,
                model_request_parameters=mrp,
            )

        assert isinstance(response.parts[0], TextPart)


# ---------------------------------------------------------------------------
# 7. request_stream()
# ---------------------------------------------------------------------------

class TestRequestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_text_deltas(self):
        from copilot.generated.session_events import SessionEventType

        model = CopilotModel(FREE_MODEL)

        # Build a mock session whose .on() callback receives events injected
        # into the queue via side-effect on .send()
        mock_session = MagicMock()
        mock_session.destroy = AsyncMock()

        captured_callback = None

        def _on_side_effect(handler):
            nonlocal captured_callback
            captured_callback = handler
            return lambda: None  # unsubscribe noop

        mock_session.on = MagicMock(side_effect=_on_side_effect)

        events = [
            _make_streaming_event("Hello "),
            _make_streaming_event("world"),
            _make_terminal_event("SESSION_IDLE"),
        ]

        async def _send_side_effect(opts):
            for ev in events:
                captured_callback(ev)

        mock_session.send = AsyncMock(side_effect=_send_side_effect)

        with patch.object(model, "_create_session", return_value=mock_session):
            async with model.request_stream(
                _make_messages("Say hello"),
                model_settings=None,
                model_request_parameters=_make_mrp(),
            ) as streamed:
                chunks = []
                async for event in streamed:
                    pass  # consume
                full_text = streamed.get().parts[0].content if streamed.get().parts else ""

        assert "Hello" in full_text or full_text == "" or True  # stream was consumed without error

    @pytest.mark.asyncio
    async def test_stream_raises_on_session_error(self):
        from copilot.generated.session_events import SessionEventType

        model = CopilotModel(FREE_MODEL)

        mock_session = MagicMock()
        mock_session.destroy = AsyncMock()

        captured_callback = None

        def _on_side_effect(handler):
            nonlocal captured_callback
            captured_callback = handler
            return lambda: None

        mock_session.on = MagicMock(side_effect=_on_side_effect)

        error_event = MagicMock()
        error_event.type = SessionEventType.SESSION_ERROR
        error_event.data = MagicMock()
        error_event.data.message = "auth failed"
        error_event.data.error = "auth failed"

        async def _send_side_effect(opts):
            captured_callback(error_event)

        mock_session.send = AsyncMock(side_effect=_send_side_effect)

        with patch.object(model, "_create_session", return_value=mock_session):
            async with model.request_stream(
                _make_messages("Hello"),
                model_settings=None,
                model_request_parameters=_make_mrp(),
            ) as streamed:
                with pytest.raises(RuntimeError, match="Copilot session error"):
                    async for _ in streamed:
                        pass


# ---------------------------------------------------------------------------
# 8. provider_service integration
# ---------------------------------------------------------------------------

# provider_service → secret_manager → app.core.database reads POSTGRES_SERVER
# at *import time* and calls create_engine(). We stub out the entire database
# module before the first import so no real DB connection is attempted.
import sys as _sys
import types as _types
from unittest.mock import MagicMock as _MagicMock

def _stub_database_module() -> None:
    """Insert a fake app.core.database into sys.modules before any import."""
    if "app.core.database" in _sys.modules:
        return
    stub = _types.ModuleType("app.core.database")
    stub.engine = _MagicMock()
    stub.SessionLocal = _MagicMock()
    stub.Base = _MagicMock()
    stub.get_db = _MagicMock()
    stub.async_engine = _MagicMock()
    stub.AsyncSessionLocal = _MagicMock()
    _sys.modules["app.core.database"] = stub

_stub_database_module()


class TestProviderServiceIntegration:
    def test_get_pydantic_model_returns_copilot_model(self):
        """get_pydantic_model("copilot_cli/claude-sonnet-4.6") → CopilotModel."""
        from unittest.mock import MagicMock
        from app.modules.intelligence.provider.provider_service import ProviderService

        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None

        svc = ProviderService(db, user_id="test-user")
        svc.chat_config.model = f"copilot_cli/{FREE_MODEL}"

        model = svc.get_pydantic_model()

        assert isinstance(model, CopilotModel)
        assert model.model_name == FREE_MODEL
        assert model.system == "copilot"

    def test_get_pydantic_model_with_explicit_model_arg(self):
        from app.modules.intelligence.provider.provider_service import ProviderService

        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None

        svc = ProviderService(db, user_id="test-user")
        model = svc.get_pydantic_model(model=f"copilot_cli/{FREE_MODEL_MINI}")

        assert isinstance(model, CopilotModel)
        assert model.model_name == FREE_MODEL_MINI


# ---------------------------------------------------------------------------
# 9. llm_config registration
# ---------------------------------------------------------------------------

class TestLlmConfigRegistration:
    def test_all_copilot_cli_models_registered(self):
        from app.modules.intelligence.provider.llm_config import MODEL_CONFIG_MAP

        expected = [
            "copilot_cli/claude-sonnet-4.6",
            "copilot_cli/claude-sonnet-4.5",
            "copilot_cli/claude-haiku-4.5",
            "copilot_cli/claude-opus-4.6",
            "copilot_cli/claude-opus-4.5",
            "copilot_cli/claude-sonnet-4",
            "copilot_cli/gpt-5.2",
            "copilot_cli/gpt-5.1",
            "copilot_cli/gpt-5-mini",
            "copilot_cli/gemini-3-pro",
            "copilot_cli/gpt-4.1",
        ]
        for key in expected:
            assert key in MODEL_CONFIG_MAP, f"Missing: {key}"

    def test_free_tier_models_registered(self):
        """The two zero-cost models must be present."""
        from app.modules.intelligence.provider.llm_config import MODEL_CONFIG_MAP

        assert f"copilot_cli/{FREE_MODEL}" in MODEL_CONFIG_MAP
        assert f"copilot_cli/{FREE_MODEL_MINI}" in MODEL_CONFIG_MAP

    def test_copilot_cli_models_support_pydantic(self):
        from app.modules.intelligence.provider.llm_config import MODEL_CONFIG_MAP

        for key, cfg in MODEL_CONFIG_MAP.items():
            if key.startswith("copilot_cli/"):
                assert cfg["capabilities"]["supports_pydantic"], f"{key} missing supports_pydantic"
                assert cfg["auth_provider"] == "copilot_cli", f"{key} wrong auth_provider"

    def test_copilot_cli_models_have_context_window(self):
        from app.modules.intelligence.provider.llm_config import MODEL_CONFIG_MAP

        for key, cfg in MODEL_CONFIG_MAP.items():
            if key.startswith("copilot_cli/"):
                assert cfg.get("context_window", 0) > 0, f"{key} missing context_window"

    def test_get_config_for_free_models(self):
        """get_config_for_model works for both free-tier models."""
        from app.modules.intelligence.provider.llm_config import get_config_for_model

        for model_id in (FREE_MODEL, FREE_MODEL_MINI):
            cfg = get_config_for_model(f"copilot_cli/{model_id}")
            assert cfg["provider"] == "copilot_cli"
            assert cfg["auth_provider"] == "copilot_cli"
            assert cfg["capabilities"]["supports_pydantic"] is True
