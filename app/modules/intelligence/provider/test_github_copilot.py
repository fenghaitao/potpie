"""
Integration test: verify github_copilot/gpt-4o works end-to-end within potpie.

Covers:
  1. llm_config  — model is registered with correct auth_provider
  2. ProviderService._build_llm_params — extra_headers injected for github_copilot
  3. ProviderService.get_pydantic_model — returns LiteLLMModel (not OpenAIModel)
  4. ProviderService.call_llm — live round-trip via litellm acompletion
  5. LiteLLMModel — pydantic-ai Model subclass makes a live request

Run:
    pytest app/modules/intelligence/provider/test_github_copilot.py -v
or for a quick smoke test without pytest:
    python app/modules/intelligence/provider/test_github_copilot.py
"""

import asyncio
import os
import sys

# ---------------------------------------------------------------------------
# 1. llm_config: model registration
# ---------------------------------------------------------------------------
def test_llm_config_github_copilot():
    from app.modules.intelligence.provider.llm_config import (
        get_config_for_model,
        MODEL_CONFIG_MAP,
    )

    model_id = "github_copilot/gpt-4o"
    assert model_id in MODEL_CONFIG_MAP, f"{model_id} missing from MODEL_CONFIG_MAP"

    cfg = get_config_for_model(model_id)
    assert cfg["provider"] == "github_copilot"
    assert cfg["auth_provider"] == "github_copilot"
    assert cfg["capabilities"]["supports_pydantic"] is True
    print("✓ llm_config: github_copilot/gpt-4o registered correctly")


# ---------------------------------------------------------------------------
# 2. _build_llm_params: extra_headers injected
# ---------------------------------------------------------------------------
def test_build_llm_params_headers(monkeypatch=None):
    import json

    # Ensure LLM_EXTRA_HEADERS is set (mirrors .env)
    extra = {"editor-version": "vscode/1.85.1", "Copilot-Integration-Id": "vscode-chat"}
    os.environ.setdefault("LLM_EXTRA_HEADERS", json.dumps(extra))

    from unittest.mock import MagicMock
    from app.modules.intelligence.provider.provider_service import ProviderService
    from app.modules.intelligence.provider.llm_config import LLMProviderConfig, get_config_for_model

    # Build a minimal ProviderService without a real DB
    svc = object.__new__(ProviderService)
    svc._api_key_cache = {}
    svc.user_id = "test-user"
    svc.db = None
    svc.user_preferences = {}

    cfg_data = get_config_for_model("github_copilot/gpt-4o")
    config = LLMProviderConfig(
        provider=cfg_data["provider"],
        model="github_copilot/gpt-4o",
        default_params=dict(cfg_data["default_params"]),
        capabilities=cfg_data["capabilities"],
        base_url=cfg_data.get("base_url"),
        api_version=cfg_data.get("api_version"),
        auth_provider=cfg_data["auth_provider"],
    )

    params = svc._build_llm_params(config)

    assert "extra_headers" in params, "extra_headers missing from params"
    headers = params["extra_headers"]
    # Must contain the copilot identity headers
    assert "Editor-Version" in headers or "editor-version" in headers, \
        f"Editor-Version missing from extra_headers: {headers}"
    print(f"✓ _build_llm_params: extra_headers present → {headers}")


# ---------------------------------------------------------------------------
# 3. get_pydantic_model: returns LiteLLMModel
# ---------------------------------------------------------------------------
def test_get_pydantic_model_returns_litellm():
    from unittest.mock import MagicMock, patch
    from app.modules.intelligence.provider.provider_service import ProviderService
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel
    from app.modules.intelligence.provider.llm_config import build_llm_provider_config

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None

    with patch.dict(os.environ, {"CHAT_MODEL": "github_copilot/gpt-4o"}):
        svc = ProviderService.create(db, "test-user")
        model = svc.get_pydantic_model()

    assert isinstance(model, LiteLLMModel), \
        f"Expected LiteLLMModel, got {type(model)}"
    assert model._model_name == "github_copilot/gpt-4o"
    print(f"✓ get_pydantic_model: returned LiteLLMModel({model._model_name})")


# ---------------------------------------------------------------------------
# 4. call_llm: live round-trip via litellm
# ---------------------------------------------------------------------------
async def test_call_llm_live():
    from unittest.mock import MagicMock, patch

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None

    with patch.dict(os.environ, {"CHAT_MODEL": "github_copilot/gpt-4o"}):
        from app.modules.intelligence.provider.provider_service import ProviderService
        svc = ProviderService.create(db, "test-user")

    messages = [{"role": "user", "content": "Reply with exactly: COPILOT_OK"}]
    response = await svc.call_llm(messages, stream=False, config_type="chat")

    assert isinstance(response, str) and len(response) > 0, \
        f"Expected non-empty string, got: {response!r}"
    print(f"✓ call_llm live response: {response!r}")


# ---------------------------------------------------------------------------
# 5. LiteLLMModel: pydantic-ai agent smoke test
# ---------------------------------------------------------------------------
async def test_litellm_model_pydantic_agent():
    from pydantic_ai import Agent
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    model = LiteLLMModel("github_copilot/gpt-4o")
    agent = Agent(model=model, system_prompt="You are a helpful assistant.")

    result = await agent.run("Reply with exactly: AGENT_OK")
    text = result.output if hasattr(result, "output") else str(result)

    assert len(text) > 0, f"Empty response from agent: {text!r}"
    print(f"✓ LiteLLMModel pydantic-ai agent response: {text!r}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n=== github_copilot/gpt-4o integration tests ===\n")

    # Unit tests (no network)
    test_llm_config_github_copilot()
    test_build_llm_params_headers()
    test_get_pydantic_model_returns_litellm()

    # Live tests (require GITHUB_COPILOT_API_KEY or OAuth token in env)
    print("\n--- Live tests (require valid Copilot credentials) ---")
    asyncio.run(test_call_llm_live())
    asyncio.run(test_litellm_model_pydantic_agent())

    print("\n✓ All tests passed.")
