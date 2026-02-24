#!/usr/bin/env python3
"""Minimal litellm github_copilot connectivity test."""
import httpx
import litellm

# Apply proxy WA
litellm.in_memory_llm_clients_cache.flush_cache()
import litellm.llms.custom_httpx.http_handler as http_handler
http_handler._DEFAULT_TIMEOUT = httpx.Timeout(timeout=60.0, connect=30.0)

COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.85.1",
    "Editor-Plugin-Version": "copilot-chat/0.11.1",
    "Copilot-Integration-Id": "vscode-chat",
}

print("Model: github_copilot/gpt-4o")
print()

response = litellm.completion(
    model="github_copilot/gpt-4o",
    messages=[{"role": "user", "content": "Say hello in one word."}],
    max_tokens=10,
    extra_headers=COPILOT_HEADERS,
)

print("Response:", response.choices[0].message.content)
