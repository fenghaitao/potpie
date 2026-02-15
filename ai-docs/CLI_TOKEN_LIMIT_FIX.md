# CLI Token Limit Fix

## Problem

When using `potpie_cli.py chat`, you may encounter this error:

```
WARNING | Pydantic-ai error: status_code: 429
message: 'Request too large for gpt-4o: Limit 30000, Requested 33926'
code: 'rate_limit_exceeded'
```

## Root Cause

The CLI chat mode accumulates conversation history without limits:
- Each turn adds user message + assistant response
- After 5-10 turns, the context becomes huge
- GPT-4o has a 30,000 TPM (tokens per minute) limit
- Large context + new query can exceed this limit

## Solution

**Implemented:** History trimming in `potpie_cli.py`

```python
MAX_HISTORY_TURNS = 5  # Keep only last 5 conversation turns

# After each response:
if len(history) > MAX_HISTORY_TURNS * 2:
    history = history[-MAX_HISTORY_TURNS * 2:]  # Keep only recent 10 messages
```

## Additional Options

### Option 1: Use a Smaller Model for Chat

```bash
# In .env, switch to GPT-4o-mini for lower token usage
CHAT_MODEL=openai/gpt-4o-mini
INFERENCE_MODEL=openai/gpt-4o-mini
```

**Benefits:**
- 4x cheaper
- Higher rate limits
- Still very capable

### Option 2: Reduce Context in Queries

Instead of:
```bash
You: "Review all the authentication code and suggest improvements"
```

Try:
```bash
You: "Review AuthService.login() method"
```

### Option 3: Use One-Shot Queries

For simple questions, use `ask` instead of `chat`:

```bash
python ./potpie_cli.py ask "What does AuthService do?" -p <project-id>
```

**Benefits:**
- No history accumulation
- Fresh context each time
- Lower token usage

### Option 4: Increase OpenAI Rate Limit

Visit https://platform.openai.com/account/limits and:
- Upgrade your OpenAI tier (paid tier has higher limits)
- Request limit increase

**Current tiers:**
- Free: 3 RPM, 40k TPM
- Tier 1: 500 RPM, 30k TPM
- Tier 2: 5000 RPM, 450k TPM

## Testing the Fix

After updating the CLI:

```bash
# Start chat
python ./potpie_cli.py chat -p <project-id>

# Have a long conversation (10+ turns)
# Should not hit token limit anymore

# Check history size
# (should stay at ~10 messages max)
```

## Token Usage Breakdown

Typical token usage per turn:

| Component | Tokens |
|-----------|--------|
| System prompt | ~500 |
| Project context | ~1,000 |
| User query | ~50-200 |
| History (5 turns) | ~2,000-5,000 |
| **Total request** | **~3,500-7,000** |
| Response | ~500-2,000 |

With 5-turn limit: Stays well under 30k TPM

Without limit (after 10 turns): Can exceed 30k TPM

## Best Practices

1. **Start fresh** - Type `exit` and restart chat for new topics
2. **Be specific** - Focused questions use fewer tokens
3. **Use `ask` for simple queries** - No history overhead
4. **Monitor token usage** - OpenAI dashboard shows your usage
5. **Upgrade tier** - If you hit limits often

## Related

- OpenAI Rate Limits: https://platform.openai.com/account/rate-limits
- Token counting: https://platform.openai.com/tokenizer
- Pricing: https://openai.com/pricing

