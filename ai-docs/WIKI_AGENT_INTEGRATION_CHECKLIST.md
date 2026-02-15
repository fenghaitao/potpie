# Wiki Agent Integration Checklist

Quick reference for integrating the Wiki Agent into Potpie.

---

## ✅ Files Created

- [x] `app/modules/intelligence/agents/chat_agents/system_agents/wiki_agent.py` - Agent implementation
- [x] `ai-docs/ADDING_WIKI_AGENT_GUIDE.md` - Complete implementation guide
- [x] `ai-docs/WIKI_AGENT_INTEGRATION_CHECKLIST.md` - This checklist

---

## 📋 Integration Steps

### **Step 1: Update Module Exports**

**File:** `app/modules/intelligence/agents/chat_agents/system_agents/__init__.py`

```python
from . import (
    blast_radius_agent,
    code_gen_agent,
    debug_agent,
    general_purpose_agent,
    integration_test_agent,
    low_level_design_agent,
    qna_agent,
    sweb_debug_agent,
    unit_test_agent,
    wiki_agent,  # ← ADD THIS
)

__all__ = [
    "blast_radius_agent",
    "code_gen_agent",
    "debug_agent",
    "general_purpose_agent",
    "integration_test_agent",
    "low_level_design_agent",
    "qna_agent",
    "sweb_debug_agent",
    "unit_test_agent",
    "wiki_agent",  # ← ADD THIS
]
```

---

### **Step 2: Register in AgentsService**

**File:** `app/modules/intelligence/agents/agents_service.py`

**Add import (around line 25-33):**
```python
from .chat_agents.system_agents import (
    blast_radius_agent,
    code_gen_agent,
    debug_agent,
    integration_test_agent,
    low_level_design_agent,
    qna_agent,
    unit_test_agent,
    wiki_agent,  # ← ADD THIS
)
```

**Add to `_system_agents()` method (around line 67-148):**
```python
def _system_agents(
    self,
    llm_provider: ProviderService,
    prompt_provider: PromptService,
    tools_provider: ToolService,
):
    return {
        # ... existing agents ...
        
        "wiki_agent": AgentWithInfo(
            id="wiki_agent",
            name="Wiki Documentation Agent",
            description="Generate comprehensive wiki documentation from code. Creates structured pages with API references, examples, and diagrams.",
            agent=wiki_agent.WikiAgent(
                llm_provider, tools_provider, prompt_provider
            ),
        ),
    }
```

---

### **Step 3: Add to CLI (Optional)**

**File:** `potpie_cli.py`

**Update agents command:**
```python
@cli.command()
def agents():
    """List available agents"""
    agents = [
        # ... existing agents ...
        ("wiki_agent", "Wiki Documentation Agent", "Generate wiki pages from code"),
    ]
```

**Update chat command:**
```python
@cli.command()
@click.option('--agent', '-a', 
              type=click.Choice([
                  'codebase_qna_agent',
                  'code_generation_agent',
                  'debugging_agent',
                  'unit_test_agent',
                  'integration_test_agent',
                  'LLD_agent',
                  'code_changes_agent',
                  'general_purpose_agent',
                  'sweb_debug_agent',
                  'wiki_agent',  # ← ADD THIS
              ]),
              default='codebase_qna_agent')
```

---

### **Step 4: Update Frontend (Optional)**

**File:** `potpie-ui/src/components/AgentSelector.tsx` (or similar)

Add wiki agent to the agent list in the UI dropdown.

---

### **Step 5: Test the Agent**

```bash
# 1. Restart backend
./start.sh

# 2. Test via CLI
python ./potpie_cli.py chat -p <project-id> -a wiki_agent

# 3. Try example queries
# - "Generate wiki documentation for the AuthService module"
# - "Create API reference for all agent classes"
# - "Document the parsing system with examples"
```

---

## 🧪 Test Queries

### **Simple Module Documentation**
```
Generate wiki documentation for the WikiAgent class
```

**Expected:** Markdown documentation with class overview, methods, examples

---

### **Full Module Documentation**
```
Create comprehensive wiki pages for the app/modules/intelligence/agents/ module
```

**Expected:** Multiple pages with:
- Module overview
- Class hierarchies
- API references
- Examples
- Cross-references

---

### **API Reference**
```
Generate API reference documentation for all system agents
```

**Expected:** Structured API docs with:
- Agent signatures
- Parameters
- Return types
- Usage examples

---

### **Confluence Export**
```
Document the authentication system and create a Confluence page in space DOCS
```

**Expected:** 
- Analysis of auth code
- Confluence page created via API
- Link to created page

---

## ✅ Verification Checklist

- [ ] `wiki_agent.py` exists and has no syntax errors
- [ ] Agent imports added to `__init__.py`
- [ ] Agent registered in `agents_service.py`
- [ ] Backend restarts without errors
- [ ] Agent appears in `GET /agents` API endpoint
- [ ] Agent works via CLI
- [ ] Agent works via Web UI
- [ ] Generated documentation is well-formatted
- [ ] Code examples in output are accurate
- [ ] Cross-references work correctly

---

## 🐛 Troubleshooting

### **Agent Not Appearing**

```bash
# Check if agent is registered
curl http://localhost:8001/api/v1/agents | jq '.[] | select(.id == "wiki_agent")'

# Should return:
# {
#   "id": "wiki_agent",
#   "name": "Wiki Documentation Agent",
#   "description": "Generate comprehensive wiki...",
#   "status": "SYSTEM"
# }
```

### **Import Errors**

```python
# Verify imports work
python -c "from app.modules.intelligence.agents.chat_agents.system_agents import wiki_agent; print('✅ Import successful')"
```

### **Agent Fails to Execute**

Check logs:
```bash
tail -f /tmp/potpie_startup.log | grep -i wiki
```

Common issues:
- Missing tools (check `tools_provider.get_tools()`)
- Model doesn't support Pydantic (set `LLM_SUPPORTS_PYDANTIC=true`)
- Token limits (see CLI_TOKEN_LIMIT_FIX.md)

---

## 📚 Documentation Updates

After integration, update:

- [ ] `ai-docs/AGENTS_GUIDE.md` - Add Wiki Agent profile
- [ ] Main `README.md` - Mention wiki generation capability
- [ ] API documentation - Document wiki agent endpoint

---

## 🎯 Example Integration Session

```bash
# 1. Add exports
vim app/modules/intelligence/agents/chat_agents/system_agents/__init__.py

# 2. Register agent
vim app/modules/intelligence/agents/agents_service.py

# 3. Restart backend
pkill -f gunicorn && pkill -f celery
./start.sh

# 4. Verify
curl http://localhost:8001/api/v1/agents | jq '.[] | select(.id == "wiki_agent")'

# 5. Test
python ./potpie_cli.py chat -p <project-id> -a wiki_agent

# 6. Try it
> Generate wiki documentation for the WikiAgent class
```

---

## ✨ Next Steps

After successful integration:

1. **Test with real projects** - Generate docs for actual modules
2. **Refine prompts** - Improve documentation quality
3. **Add templates** - Create wiki page templates
4. **Integrate with CI/CD** - Auto-generate docs on commits
5. **Export automation** - Batch export to wiki platforms

---

## 📝 Summary

**Total files to modify:** 2-3 files
**Time required:** ~15 minutes
**Difficulty:** Easy (copy-paste integration)

The Wiki Agent is ready to use - just follow the integration steps above!

