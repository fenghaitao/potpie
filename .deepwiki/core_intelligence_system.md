2-Core Intelligence System

# Page: Core Intelligence System

# Core Intelligence System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/modules/intelligence/agents/agents_service.py](app/modules/intelligence/agents/agents_service.py)
- [app/modules/intelligence/agents/chat_agents/auto_router_agent.py](app/modules/intelligence/agents/chat_agents/auto_router_agent.py)
- [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py](app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py)
- [app/modules/intelligence/provider/anthropic_caching_model.py](app/modules/intelligence/provider/anthropic_caching_model.py)
- [app/modules/intelligence/provider/llm_config.py](app/modules/intelligence/provider/llm_config.py)
- [app/modules/intelligence/provider/provider_service.py](app/modules/intelligence/provider/provider_service.py)

</details>



## Purpose and Scope

The Core Intelligence System is the AI/LLM integration layer that powers all intelligent interactions in Potpie. This system provides unified abstractions for multiple LLM providers, orchestrates specialized agents, and manages the execution pipeline for AI-powered code analysis tasks. 

This document covers the architecture, components, and orchestration mechanisms of the intelligence layer. For detailed information on specific topics, see:
- Provider implementation details: [Provider Service (LLM Abstraction)](#2.1)
- Agent routing and execution: [Agent System Architecture](#2.2)
- Pre-built agents: [System Agents](#2.3)
- User-defined agents: [Custom Agents](#2.4)
- Execution strategies: [Agent Execution Pipeline](#2.5)
- Prompt handling: [Prompt Management](#2.6)

---

## System Architecture

The Core Intelligence System is organized into four primary service layers that work together to provide AI-powered functionality:

### High-Level Component Diagram

```mermaid
graph TB
    subgraph "External Layer"
        LLM_PROVIDERS["LLM Providers<br/>OpenAI, Anthropic,<br/>DeepSeek, Gemini"]
        SECRET_MGR["SecretManager<br/>API Key Storage"]
    end
    
    subgraph "Service Layer"
        PROVIDER_SVC["ProviderService<br/>app/modules/intelligence/provider/provider_service.py"]
        AGENT_SVC["AgentsService<br/>app/modules/intelligence/agents/agents_service.py"]
        PROMPT_SVC["PromptService<br/>app/modules/intelligence/prompts/prompt_service.py"]
        TOOL_SVC["ToolService<br/>app/modules/intelligence/tools/tool_service.py"]
    end
    
    subgraph "Orchestration Layer"
        SUPERVISOR["SupervisorAgent<br/>Routing Logic"]
        AUTO_ROUTER["AutoRouterAgent<br/>Direct Dispatch"]
    end
    
    subgraph "Execution Layer"
        SYSTEM_AGENTS["System Agents<br/>QnA, Debug, CodeGen, etc."]
        CUSTOM_AGENTS["Custom Agents<br/>User-Defined"]
    end
    
    subgraph "Implementation Layer"
        PYDANTIC_RAG["PydanticRagAgent<br/>Structured Output"]
        PYDANTIC_MULTI["PydanticMultiAgent<br/>Multi-Agent Delegation"]
        LANGCHAIN["LangchainAgent<br/>Legacy Support"]
    end
    
    AGENT_SVC --> PROVIDER_SVC
    AGENT_SVC --> PROMPT_SVC
    AGENT_SVC --> TOOL_SVC
    AGENT_SVC --> SUPERVISOR
    
    SUPERVISOR --> AUTO_ROUTER
    AUTO_ROUTER --> SYSTEM_AGENTS
    AUTO_ROUTER --> CUSTOM_AGENTS
    
    SYSTEM_AGENTS --> PYDANTIC_RAG
    SYSTEM_AGENTS --> PYDANTIC_MULTI
    CUSTOM_AGENTS --> PYDANTIC_RAG
    
    PYDANTIC_RAG --> PROVIDER_SVC
    PYDANTIC_MULTI --> PROVIDER_SVC
    LANGCHAIN --> PROVIDER_SVC
    
    PROVIDER_SVC --> SECRET_MGR
    PROVIDER_SVC --> LLM_PROVIDERS
    
    PYDANTIC_RAG -.->|uses| TOOL_SVC
    PYDANTIC_MULTI -.->|uses| TOOL_SVC
```

**Sources:**
- [app/modules/intelligence/provider/provider_service.py:1-1600]()
- [app/modules/intelligence/agents/agents_service.py:1-203]()
- [app/modules/intelligence/agents/chat_agents/auto_router_agent.py:1-38]()

---

## Provider Service: Multi-LLM Abstraction

The `ProviderService` class provides a unified interface for interacting with multiple LLM providers. It handles API key management, retry logic, model configuration, and provider-specific adaptations.

### ProviderService Architecture

```mermaid
graph TB
    subgraph "ProviderService Initialization"
        PROVIDER_SVC["ProviderService.__init__<br/>db, user_id"]
        USER_PREFS["UserPreferences<br/>Query from DB"]
        CHAT_CONFIG["chat_config: LLMProviderConfig<br/>build_llm_provider_config()"]
        INFERENCE_CONFIG["inference_config: LLMProviderConfig<br/>build_llm_provider_config()"]
    end
    
    subgraph "API Key Management"
        API_KEY_CACHE["_api_key_cache<br/>Dict[str, Optional[str]]"]
        GET_API_KEY["_get_api_key(provider)<br/>Cached Lookup"]
        ENV_VAR["Environment Variable<br/>LLM_API_KEY"]
        SECRET_MANAGER["SecretManager.get_secret<br/>User-Specific Keys"]
    end
    
    subgraph "LLM Call Methods"
        CALL_LLM["call_llm()<br/>Basic Completion"]
        CALL_STRUCTURED["call_llm_with_structured_output()<br/>Pydantic Schema"]
        CALL_SPECIFIC["call_llm_with_specific_model()<br/>Override Model"]
        ROBUST_DECORATOR["@robust_llm_call<br/>Retry Logic"]
    end
    
    subgraph "Configuration"
        MODEL_CONFIG_MAP["MODEL_CONFIG_MAP<br/>llm_config.py"]
        AVAILABLE_MODELS["AVAILABLE_MODELS<br/>26 models defined"]
        BUILD_LLM_PARAMS["_build_llm_params()<br/>Provider-Specific Params"]
    end
    
    PROVIDER_SVC --> USER_PREFS
    USER_PREFS --> CHAT_CONFIG
    USER_PREFS --> INFERENCE_CONFIG
    
    CHAT_CONFIG --> BUILD_LLM_PARAMS
    INFERENCE_CONFIG --> BUILD_LLM_PARAMS
    BUILD_LLM_PARAMS --> GET_API_KEY
    
    GET_API_KEY --> API_KEY_CACHE
    API_KEY_CACHE --> ENV_VAR
    API_KEY_CACHE --> SECRET_MANAGER
    
    CALL_LLM --> ROBUST_DECORATOR
    CALL_STRUCTURED --> ROBUST_DECORATOR
    CALL_SPECIFIC --> ROBUST_DECORATOR
    
    ROBUST_DECORATOR -.->|uses| MODEL_CONFIG_MAP
    BUILD_LLM_PARAMS -.->|uses| AVAILABLE_MODELS
```

**Sources:**
- [app/modules/intelligence/provider/provider_service.py:472-580]()
- [app/modules/intelligence/provider/provider_service.py:645-681]()
- [app/modules/intelligence/provider/llm_config.py:1-359]()

### Supported Models and Providers

The system supports 26 LLM models across multiple providers, defined in `AVAILABLE_MODELS`:

| Provider | Models | Capabilities |
|----------|--------|--------------|
| **OpenAI** | `gpt-5.2`, `gpt-5.1`, `gpt-5-mini` | Pydantic, Streaming, Vision, Tool Parallelism |
| **Anthropic** | `claude-sonnet-4-5`, `claude-haiku-4-5`, `claude-opus-4-1`, `claude-sonnet-4`, `claude-3-7-sonnet`, `claude-3-5-haiku`, `claude-opus-4-5` | Pydantic, Streaming, Vision, Tool Parallelism, Prompt Caching |
| **DeepSeek** | `deepseek-chat-v3-0324` | Pydantic, Streaming, Tool Parallelism |
| **Meta-Llama** | `llama-3.3-70b-instruct` | Pydantic, Streaming, Tool Parallelism |
| **Gemini** | `gemini-2.0-flash-001`, `gemini-2.5-pro-preview`, `gemini-3-pro-preview` | Pydantic, Streaming, Vision, Tool Parallelism |
| **Z-AI** | `glm-4.7` | Pydantic, Streaming, Vision |

**Sources:**
- [app/modules/intelligence/provider/provider_service.py:330-460]()
- [app/modules/intelligence/provider/llm_config.py:9-214]()

### Retry Logic and Error Handling

The `ProviderService` implements sophisticated retry logic with exponential backoff to handle transient errors:

```mermaid
graph LR
    CALL["LLM API Call"]
    ERROR{"Error<br/>Occurred?"}
    RECOVERABLE{"is_recoverable_error()<br/>Check Error Type"}
    RETRY_COUNT{"Retry Count <br/> Max Retries?"}
    BACKOFF["calculate_backoff_time()<br/>Exponential + Jitter"]
    SLEEP["asyncio.sleep(delay)"]
    SUCCESS["Return Response"]
    FAIL["Raise Exception"]
    
    CALL --> ERROR
    ERROR -->|No| SUCCESS
    ERROR -->|Yes| RECOVERABLE
    RECOVERABLE -->|No| FAIL
    RECOVERABLE -->|Yes| RETRY_COUNT
    RETRY_COUNT -->|Yes| BACKOFF
    RETRY_COUNT -->|No| FAIL
    BACKOFF --> SLEEP
    SLEEP --> CALL
```

The `RetrySettings` class configures retry behavior:

| Setting | Default | Description |
|---------|---------|-------------|
| `max_retries` | 8 | Maximum retry attempts |
| `base_delay` | 2.0s | Base delay for exponential backoff |
| `max_delay` | 120.0s | Maximum delay between retries |
| `step_increase` | 1.8 | Exponential growth factor |
| `jitter_factor` | 0.2 | Random variance to prevent thundering herd |

**Sources:**
- [app/modules/intelligence/provider/provider_service.py:75-259]()
- [app/modules/intelligence/provider/provider_service.py:116-161]()
- [app/modules/intelligence/provider/provider_service.py:163-177]()

### Anthropic Prompt Caching

For Anthropic models, the `CachingAnthropicModel` class automatically enables prompt caching to reduce costs and latency:

```mermaid
graph TB
    subgraph "Cache Strategy"
        TOOLS["Tool Definitions<br/>cache_control on last tool"]
        SYSTEM_PROMPT["System Prompt<br/>Split at CACHE_BREAKPOINT_MARKER"]
        STATIC["Static Content<br/>Cached (before marker)"]
        DYNAMIC["Dynamic Content<br/>Not Cached (after marker)"]
    end
    
    subgraph "Cache Metrics"
        USAGE["BetaMessage.usage"]
        CACHE_READ["cache_read_input_tokens<br/>90% cost savings"]
        CACHE_WRITE["cache_creation_input_tokens<br/>25% extra cost, 5min TTL"]
        UNCACHED["input_tokens<br/>100% cost"]
    end
    
    subgraph "Logging"
        METRICS_FILE[".debug/anthropic_cache_metrics.jsonl"]
        SESSION_TOTALS["Session Totals<br/>Cumulative Savings"]
    end
    
    TOOLS --> CACHE_READ
    STATIC --> CACHE_READ
    DYNAMIC --> UNCACHED
    
    CACHE_READ --> USAGE
    CACHE_WRITE --> USAGE
    UNCACHED --> USAGE
    
    USAGE --> METRICS_FILE
    METRICS_FILE --> SESSION_TOTALS
```

Cache hit rates can achieve up to 90% cost reduction and 85% latency improvement for repeated requests with the same tools/prompts.

**Sources:**
- [app/modules/intelligence/provider/anthropic_caching_model.py:1-693]()
- [app/modules/intelligence/provider/anthropic_caching_model.py:419-474]()
- [app/modules/intelligence/provider/anthropic_caching_model.py:544-568]()

---

## Agent Service: Orchestration and Routing

The `AgentsService` class manages the lifecycle of AI agents, routing user queries to the appropriate specialized agent.

### AgentsService Initialization

```mermaid
graph TB
    AGENT_SVC["AgentsService.__init__<br/>db, llm_provider, prompt_provider, tools_provider"]
    
    SYSTEM_AGENTS["_system_agents()<br/>Dictionary of AgentWithInfo"]
    QNA["codebase_qna_agent<br/>QnAAgent"]
    DEBUG["debugging_agent<br/>DebugAgent"]
    UNIT_TEST["unit_test_agent<br/>UnitTestAgent"]
    INTEG_TEST["integration_test_agent<br/>IntegrationTestAgent"]
    LLD["LLD_agent<br/>LowLevelDesignAgent"]
    CODE_CHANGES["code_changes_agent<br/>BlastRadiusAgent"]
    CODE_GEN["code_generation_agent<br/>CodeGenAgent"]
    GENERAL["general_purpose_agent<br/>GeneralPurposeAgent"]
    SWEB_DEBUG["sweb_debug_agent<br/>SWEBDebugAgent"]
    
    SUPERVISOR["SupervisorAgent<br/>llm_provider, system_agents"]
    CUSTOM_SVC["CustomAgentService<br/>db, llm_provider, tools_provider"]
    
    AGENT_SVC --> SYSTEM_AGENTS
    SYSTEM_AGENTS --> QNA
    SYSTEM_AGENTS --> DEBUG
    SYSTEM_AGENTS --> UNIT_TEST
    SYSTEM_AGENTS --> INTEG_TEST
    SYSTEM_AGENTS --> LLD
    SYSTEM_AGENTS --> CODE_CHANGES
    SYSTEM_AGENTS --> CODE_GEN
    SYSTEM_AGENTS --> GENERAL
    SYSTEM_AGENTS --> SWEB_DEBUG
    
    AGENT_SVC --> SUPERVISOR
    AGENT_SVC --> CUSTOM_SVC
```

**Sources:**
- [app/modules/intelligence/agents/agents_service.py:47-66]()
- [app/modules/intelligence/agents/agents_service.py:68-149]()

### Request Routing Flow

The routing flow determines which agent handles a user query:

```mermaid
sequenceDiagram
    participant User
    participant ConversationService
    participant AgentsService
    participant SupervisorAgent
    participant AutoRouterAgent
    participant SpecializedAgent
    
    User->>ConversationService: POST /conversations/{id}/message
    ConversationService->>AgentsService: execute_stream(ctx)
    AgentsService->>SupervisorAgent: run_stream(ctx)
    
    alt ctx.curr_agent_id is set
        SupervisorAgent->>AutoRouterAgent: run_stream(ctx)
        Note over AutoRouterAgent: Returns agent from ctx.curr_agent_id
        AutoRouterAgent->>SpecializedAgent: run_stream(ctx)
    else No agent_id
        Note over SupervisorAgent: Classifies query and routes
        SupervisorAgent->>SpecializedAgent: run_stream(ctx)
    end
    
    SpecializedAgent-->>User: Stream response chunks
```

**Sources:**
- [app/modules/intelligence/agents/agents_service.py:151-156]()
- [app/modules/intelligence/agents/chat_agents/auto_router_agent.py:13-37]()

### ChatContext Structure

Agents receive a `ChatContext` object containing all information needed for execution:

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | `str` | User identifier |
| `project_id` | `str` | Project identifier for knowledge graph |
| `conversation_id` | `str` | Conversation identifier |
| `query` | `str` | User's current query |
| `chat_history` | `List[Message]` | Previous conversation turns |
| `curr_agent_id` | `Optional[str]` | Pre-selected agent ID (bypasses routing) |
| `run_id` | `str` | Unique run identifier for streaming |
| `image_urls` | `Optional[List[str]]` | Image attachments for multimodal context |

**Sources:**
- Implementation references in agent execution files

---

## Agent Execution Strategies

Agents implement the `ChatAgent` interface and use one of several execution strategies:

### PydanticRagAgent vs PydanticMultiAgent

```mermaid
graph TB
    subgraph "Agent Selection Logic"
        SUPPORTS_PYDANTIC{"llm_provider.supports_pydantic()?"}
        SHOULD_USE_MULTI{"MultiAgentConfig.should_use_multi_agent()?"}
    end
    
    subgraph "PydanticRagAgent"
        RAG["Single Agent Execution"]
        RAG_TOOLS["Direct Tool Access"]
        RAG_LLM["call_llm_with_structured_output()"]
        RAG_STREAM["Stream responses"]
    end
    
    subgraph "PydanticMultiAgent"
        MULTI["Multi-Agent Orchestration"]
        DELEGATES["Delegate Agents<br/>THINK_EXECUTE, JIRA, GITHUB, etc."]
        MULTI_ROUTE["Route to Sub-Agents"]
        MULTI_LLM["call_llm_with_structured_output()"]
    end
    
    SUPPORTS_PYDANTIC -->|Yes| SHOULD_USE_MULTI
    SUPPORTS_PYDANTIC -->|No| RAG
    
    SHOULD_USE_MULTI -->|Yes| MULTI
    SHOULD_USE_MULTI -->|No| RAG
    
    RAG --> RAG_TOOLS
    RAG_TOOLS --> RAG_LLM
    RAG_LLM --> RAG_STREAM
    
    MULTI --> DELEGATES
    DELEGATES --> MULTI_ROUTE
    MULTI_ROUTE --> MULTI_LLM
```

**Sources:**
- [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py:37-110]()

### Tool Integration

Agents access tools through the `ToolService`:

```mermaid
graph LR
    AGENT["Agent (e.g., QnAAgent)"]
    TOOL_SVC["ToolService.get_tools()"]
    TOOL_REGISTRY["Tool Registry<br/>fetch_file_tool<br/>analyze_code_tool<br/>web_search_tool<br/>etc."]
    
    PYDANTIC_AGENT["PydanticRagAgent<br/>or PydanticMultiAgent"]
    
    LLM_DECISION["LLM decides which<br/>tools to call"]
    TOOL_EXEC["Tool Execution<br/>arun(args)"]
    TOOL_RESULT["Tool Result<br/>Back to LLM"]
    
    AGENT --> TOOL_SVC
    TOOL_SVC --> TOOL_REGISTRY
    TOOL_REGISTRY --> PYDANTIC_AGENT
    
    PYDANTIC_AGENT --> LLM_DECISION
    LLM_DECISION --> TOOL_EXEC
    TOOL_EXEC --> TOOL_RESULT
    TOOL_RESULT --> PYDANTIC_AGENT
```

For detailed information on available tools and their implementations, see [Tool System](#5).

**Sources:**
- [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py:57-62]()

---

## Configuration and Model Selection

Model selection follows a priority hierarchy:

### Configuration Priority Order

```mermaid
graph TB
    PRIORITY1["1. Environment Variables<br/>CHAT_MODEL, INFERENCE_MODEL"]
    PRIORITY2["2. User Preferences<br/>UserPreferences.preferences"]
    PRIORITY3["3. System Defaults<br/>DEFAULT_CHAT_MODEL, DEFAULT_INFERENCE_MODEL"]
    
    BUILD_CONFIG["build_llm_provider_config()<br/>config_type='chat' or 'inference'"]
    
    LLM_PROVIDER_CONFIG["LLMProviderConfig<br/>provider, model, default_params, capabilities"]
    
    PRIORITY1 -->|if set| BUILD_CONFIG
    PRIORITY2 -->|if PRIORITY1 not set| BUILD_CONFIG
    PRIORITY3 -->|if PRIORITY1,2 not set| BUILD_CONFIG
    
    BUILD_CONFIG --> LLM_PROVIDER_CONFIG
```

**Sources:**
- [app/modules/intelligence/provider/llm_config.py:320-359]()
- [app/modules/intelligence/provider/provider_service.py:482-492]()

### Model Capability Detection

Each model's capabilities are defined in `MODEL_CONFIG_MAP`:

| Capability | Description | Models |
|------------|-------------|--------|
| `supports_pydantic` | Structured output via Pydantic schemas | OpenAI, Anthropic, DeepSeek, Meta-Llama, Gemini |
| `supports_streaming` | Server-Sent Events streaming | All models |
| `supports_vision` | Multimodal image inputs | OpenAI, Anthropic, Gemini, Z-AI |
| `supports_tool_parallelism` | Parallel tool execution | OpenAI, Anthropic, DeepSeek, Meta-Llama, Gemini |

Capabilities can be overridden via environment variables:

- `LLM_SUPPORTS_PYDANTIC`
- `LLM_SUPPORTS_STREAMING`
- `LLM_SUPPORTS_VISION`
- `LLM_SUPPORTS_TOOL_PARALLELISM`

**Sources:**
- [app/modules/intelligence/provider/llm_config.py:217-251]()
- [app/modules/intelligence/provider/llm_config.py:240-250]()

---

## Code Entity Mapping

The following table maps system concepts to concrete code entities:

| System Concept | Code Entity | File Location |
|----------------|-------------|---------------|
| Provider abstraction | `ProviderService` | [app/modules/intelligence/provider/provider_service.py:472]() |
| Model configuration | `LLMProviderConfig` | [app/modules/intelligence/provider/llm_config.py:217]() |
| Model registry | `MODEL_CONFIG_MAP` | [app/modules/intelligence/provider/llm_config.py:9]() |
| Available models | `AVAILABLE_MODELS` | [app/modules/intelligence/provider/provider_service.py:331]() |
| Retry logic | `@robust_llm_call` decorator | [app/modules/intelligence/provider/provider_service.py:206]() |
| Retry settings | `RetrySettings` | [app/modules/intelligence/provider/provider_service.py:75]() |
| Error recovery | `is_recoverable_error()` | [app/modules/intelligence/provider/provider_service.py:116]() |
| Backoff calculation | `calculate_backoff_time()` | [app/modules/intelligence/provider/provider_service.py:163]() |
| Anthropic caching | `CachingAnthropicModel` | [app/modules/intelligence/provider/anthropic_caching_model.py:420]() |
| Agent orchestration | `AgentsService` | [app/modules/intelligence/agents/agents_service.py:47]() |
| System agents | `_system_agents()` | [app/modules/intelligence/agents/agents_service.py:68]() |
| Agent routing | `SupervisorAgent` | Referenced in [app/modules/intelligence/agents/agents_service.py:61]() |
| Direct dispatch | `AutoRouterAgent` | [app/modules/intelligence/agents/chat_agents/auto_router_agent.py:13]() |
| Single-agent execution | `PydanticRagAgent` | Referenced in [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py:105]() |
| Multi-agent orchestration | `PydanticMultiAgent` | Referenced in [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py:95]() |
| General purpose agent | `GeneralPurposeAgent` | [app/modules/intelligence/agents/chat_agents/system_agents/general_purpose_agent.py:26]() |

---

## Summary

The Core Intelligence System provides a robust, multi-provider AI integration layer with the following key characteristics:

1. **Provider Abstraction**: Unified interface across 26 models from 6 providers via `ProviderService`
2. **Resilient Execution**: Exponential backoff retry logic with configurable settings
3. **Cost Optimization**: Automatic prompt caching for Anthropic models (up to 90% cost reduction)
4. **Agent Orchestration**: Hierarchical routing through `SupervisorAgent` and `AutoRouterAgent`
5. **Flexible Execution**: Support for single-agent (`PydanticRagAgent`) and multi-agent (`PydanticMultiAgent`) strategies
6. **Configuration Priority**: Environment variables → User preferences → System defaults
7. **Tool Integration**: Agents access specialized tools through `ToolService`

For implementation details on specific components, refer to the child pages of this section.