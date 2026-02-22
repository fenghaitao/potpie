"""
Proper pydantic-ai Model subclass that calls litellm.acompletion directly.

Handles providers like github_copilot that use OAuth (no API key needed)
and any other LiteLLM-supported provider.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from pydantic_ai._parts_manager import ModelResponsePartsManager
from pydantic_ai._utils import now_utc as _now_utc
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.usage import RequestUsage

from app.modules.utils.logger import setup_logger

try:
    import litellm
except ImportError as e:
    raise ImportError("Please install `litellm` to use LiteLLMModel") from e

logger = setup_logger(__name__)

__all__ = ("LiteLLMModel",)

# GitHub Copilot requires these headers for every request
_COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.85.1",
    "Copilot-Integration-Id": "vscode-chat",
}


class LiteLLMModel(Model):
    """A pydantic-ai Model that delegates to litellm.acompletion.

    Works for any LiteLLM provider, including github_copilot (OAuth, no API key).
    """

    def __init__(self, model_name: str, extra_headers: dict | None = None) -> None:
        super().__init__()
        self._model_name = model_name
        self._extra_headers: dict = dict(extra_headers or {})
        if model_name.startswith("github_copilot/"):
            # Merge copilot headers (caller headers take precedence)
            merged = dict(_COPILOT_HEADERS)
            merged.update(self._extra_headers)
            self._extra_headers = merged

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def system(self) -> str:
        return "litellm"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        kwargs = self._build_kwargs(messages, model_request_parameters, model_settings, stream=False)
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            logger.error(f"LiteLLMModel.request error for {self._model_name}: {e}")
            raise
        return self._process_response(response)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncIterator[StreamedResponse]:
        kwargs = self._build_kwargs(messages, model_request_parameters, model_settings, stream=True)
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            logger.error(f"LiteLLMModel.request_stream error for {self._model_name}: {e}")
            raise
        yield LiteLLMStreamedResponse(
            model_request_parameters=model_request_parameters,
            response=response,
            model_name=self._model_name,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_kwargs(
        self,
        messages: list[ModelMessage],
        params: ModelRequestParameters,
        settings: Any,
        stream: bool,
    ) -> dict[str, Any]:
        litellm_messages = _map_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "messages": litellm_messages,
            "stream": stream,
        }
        if self._extra_headers:
            kwargs["extra_headers"] = self._extra_headers

        tools = _get_tools(params)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto" if params.allow_text_output else "required"

        if settings:
            for src, dst in [
                ("temperature", "temperature"),
                ("max_tokens", "max_tokens"),
                ("top_p", "top_p"),
                ("stop_sequences", "stop"),
            ]:
                val = settings.get(src) if hasattr(settings, "get") else getattr(settings, src, None)
                if val is not None:
                    kwargs[dst] = val

        return kwargs

    def _process_response(self, response: Any) -> ModelResponse:
        parts: list[ModelResponsePart] = []
        choice = response.choices[0]

        if choice.message.content:
            parts.append(TextPart(content=choice.message.content))

        for tc in choice.message.tool_calls or []:
            parts.append(
                ToolCallPart(
                    tool_name=tc.function.name,
                    args=tc.function.arguments or "{}",
                    tool_call_id=tc.id,
                )
            )

        finish_map = {
            "stop": "stop",
            "length": "length",
            "tool_calls": "tool_call",
            "content_filter": "content_filter",
        }

        usage = RequestUsage()
        if hasattr(response, "usage") and response.usage:
            usage = RequestUsage(
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
            )

        return ModelResponse(
            parts=parts,
            usage=usage,
            model_name=getattr(response, "model", self._model_name),
            timestamp=_now_utc(),
            provider_name="litellm",
            provider_response_id=getattr(response, "id", None),
            finish_reason=finish_map.get(choice.finish_reason or "", "stop"),
        )


class LiteLLMStreamedResponse(StreamedResponse):
    """Streamed response for LiteLLMModel."""

    def __init__(
        self,
        model_request_parameters: ModelRequestParameters,
        response: Any,
        model_name: str,
    ) -> None:
        super().__init__(model_request_parameters)
        self._response = response
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return "litellm"

    @property
    def provider_url(self) -> str | None:
        return None

    @property
    def timestamp(self) -> datetime:
        return _now_utc()

    async def _get_event_iterator(self) -> AsyncIterator[Any]:
        async for chunk in self._response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                for event in self._parts_manager.handle_text_delta(
                    vendor_part_id=0, content=delta.content
                ):
                    yield event

            for tc in delta.tool_calls or []:
                vendor_id = getattr(tc, "index", None)
                event = self._parts_manager.handle_tool_call_delta(
                    vendor_part_id=vendor_id,
                    tool_name=getattr(tc.function, "name", None) if tc.function else None,
                    args=getattr(tc.function, "arguments", None) if tc.function else None,
                    tool_call_id=getattr(tc, "id", None),
                )
                if event is not None:
                    yield event

            if hasattr(chunk, "usage") and chunk.usage:
                self._usage = RequestUsage(
                    input_tokens=getattr(chunk.usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(chunk.usage, "completion_tokens", 0) or 0,
                )


# ------------------------------------------------------------------
# Message mapping helpers
# ------------------------------------------------------------------

def _map_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    result.append({"role": "system", "content": part.content})
                elif isinstance(part, UserPromptPart):
                    content = part.content
                    result.append({"role": "user", "content": content if isinstance(content, str) else str(content)})
                elif isinstance(part, ToolReturnPart):
                    result.append({
                        "role": "tool",
                        "tool_call_id": part.tool_call_id,
                        "content": part.model_response_str(),
                    })
                elif isinstance(part, RetryPromptPart):
                    if part.tool_name is None:
                        result.append({"role": "user", "content": part.model_response()})
                    else:
                        result.append({
                            "role": "tool",
                            "tool_call_id": part.tool_call_id,
                            "content": part.model_response(),
                        })
        elif isinstance(msg, ModelResponse):
            text_parts = []
            tool_calls = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    text_parts.append(part.content)
                elif isinstance(part, ThinkingPart):
                    pass  # skip thinking in outgoing messages
                elif isinstance(part, ToolCallPart):
                    tool_calls.append({
                        "id": part.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": part.tool_name,
                            "arguments": part.args_as_json_str(),
                        },
                    })
            assistant: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                assistant["content"] = "\n\n".join(text_parts)
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            result.append(assistant)
    return result


def _get_tools(params: ModelRequestParameters) -> list[dict[str, Any]]:
    if not params.tool_defs:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description or "",
                "parameters": td.parameters_json_schema,
            },
        }
        for td in params.tool_defs.values()
    ]
