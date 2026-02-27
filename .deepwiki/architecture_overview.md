1.2-Architecture Overview

# Page: Architecture Overview

# Architecture Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env.template](.env.template)
- [app/main.py](app/main.py)
- [app/modules/conversations/conversation/conversation_controller.py](app/modules/conversations/conversation/conversation_controller.py)
- [app/modules/conversations/conversation/conversation_schema.py](app/modules/conversations/conversation/conversation_schema.py)
- [app/modules/conversations/conversation/conversation_service.py](app/modules/conversations/conversation/conversation_service.py)
- [app/modules/conversations/conversations_router.py](app/modules/conversations/conversations_router.py)
- [requirements.txt](requirements.txt)

</details>



## Purpose and Scope

This document provides a high-level technical overview of the Potpie system architecture, describing the six primary layers, their interactions, and the key components that enable AI-powered code analysis and conversation. The architecture is organized around a FastAPI application that coordinates between modular service layers, polyglot data stores, and external AI providers.

For detailed information about specific subsystems:
- Configuration and environment setup: see [System Configuration](#1.4)
- API endpoint specifications: see [API Reference](#1.3)
- Individual service modules are documented in their respective sections (sections [2](#2) through [10](#10))

---

## System Layers

The Potpie architecture is organized into six logical layers, each with distinct responsibilities. The following diagram maps high-level layer names to their concrete implementations in the codebase.

### Layer Architecture Diagram

```mermaid
graph TB
    subgraph ClientLayer["Client Layer"]
        UI["Frontend UI<br/>(External)"]
        APIClients["API Clients<br/>(External)"]
    end
    
    subgraph APIGatewayLayer["API Gateway Layer"]
        FastAPIApp["FastAPI Application<br/>app/main.py:MainApp"]
        CORSMiddleware["CORSMiddleware<br/>app/main.py:107-113"]
        LoggingMiddleware["LoggingContextMiddleware<br/>app/modules/utils/logging_middleware.py"]
        SentryInit["Sentry Error Tracking<br/>app/main.py:64-87"]
        PhoenixTracing["Phoenix Tracing<br/>app/main.py:89-99"]
    end
    
    subgraph CoreServices["Core Service Modules"]
        AuthRouter["auth_router<br/>app/modules/auth/auth_router.py"]
        ConvRouter["conversations_router<br/>app/modules/conversations/conversations_router.py"]
        ParsingRouter["parsing_router<br/>app/modules/parsing/graph_construction/parsing_router.py"]
        AgentsRouter["agent_router<br/>app/modules/intelligence/agents/agents_router.py"]
        ProjectsRouter["projects_router<br/>app/modules/projects/projects_router.py"]
    end
    
    subgraph ServiceLayer["Service Implementation Layer"]
        ConvService["ConversationService<br/>app/modules/conversations/conversation/conversation_service.py"]
        AgentService["AgentsService<br/>app/modules/intelligence/agents/agents_service.py"]
        ProviderService["ProviderService<br/>app/modules/intelligence/provider/provider_service.py"]
        ProjectService["ProjectService<br/>app/modules/projects/projects_service.py"]
        AuthService["UnifiedAuthService<br/>app/modules/auth/auth_service.py"]
    end
    
    subgraph DataLayer["Data Persistence Layer"]
        PostgresDB["PostgreSQL<br/>POSTGRES_SERVER"]
        Neo4jDB["Neo4j<br/>NEO4J_URI"]
        RedisDB["Redis<br/>REDISHOST:REDISPORT"]
        FirebaseDB["Firebase<br/>FIREBASE_SERVICE_ACCOUNT"]
    end
    
    subgraph ExternalLayer["External Integrations"]
        LLMProviders["LLM Providers<br/>via ProviderService"]
        GitHubAPI["GitHub API<br/>via CodeProviderService"]
        PostHogAPI["PostHog Analytics<br/>POSTHOG_API_KEY"]
    end
    
    UI --> FastAPIApp
    APIClients --> FastAPIApp
    FastAPIApp --> CORSMiddleware
    FastAPIApp --> LoggingMiddleware
    FastAPIApp --> SentryInit
    FastAPIApp --> PhoenixTracing
    
    FastAPIApp --> AuthRouter
    FastAPIApp --> ConvRouter
    FastAPIApp --> ParsingRouter
    FastAPIApp --> AgentsRouter
    FastAPIApp --> ProjectsRouter
    
    ConvRouter --> ConvService
    AgentsRouter --> AgentService
    ParsingRouter --> ProjectService
    
    ConvService --> AgentService
    ConvService --> ProviderService
    AgentService --> ProviderService
    
    ConvService --> PostgresDB
    ConvService --> RedisDB
    ProjectService --> PostgresDB
    ProjectService --> Neo4jDB
    AuthService --> PostgresDB
    AuthService --> FirebaseDB
    
    ProviderService --> LLMProviders
    ProjectService --> GitHubAPI
    FastAPIApp -.->|telemetry| PostHogAPI
```

**Sources:** [app/main.py:1-217](), [app/modules/conversations/conversation/conversation_service.py:73-109](), [.env.template:1-116]()

---

## Core Components

The system is built around five core service modules that provide the primary business logic. Each module follows a three-tier pattern: Router → Controller → Service.

### Service Module Mapping

| Module | Router | Controller/Service | Database | Purpose |
|--------|--------|-------------------|----------|---------|
| Authentication | `auth_router` [app/modules/auth/auth_router.py]() | `UnifiedAuthService` | PostgreSQL, Firebase | Multi-provider authentication, user identity management |
| Conversations | `conversations_router` [app/modules/conversations/conversations_router.py]() | `ConversationController`, `ConversationService` [app/modules/conversations/conversation/conversation_service.py:73-165]() | PostgreSQL, Redis | Chat session management, message streaming |
| Parsing | `parsing_router` [app/modules/parsing/graph_construction/parsing_router.py]() | `ParsingController`, Code graph services | Neo4j, PostgreSQL | Repository ingestion, AST graph construction |
| Agents | `agent_router` [app/modules/intelligence/agents/agents_router.py]() | `AgentsService` [app/modules/conversations/conversation/conversation_service.py:102]() | PostgreSQL | AI agent orchestration, tool execution |
| Projects | `projects_router` [app/modules/projects/projects_router.py]() | `ProjectService` [app/modules/conversations/conversation/conversation_service.py:97]() | PostgreSQL, Neo4j | Repository metadata management |

**Sources:** [app/main.py:147-171](), [app/modules/conversations/conversation/conversation_service.py:73-109]()

---

## FastAPI Application Initialization

The main application follows a structured initialization pattern that sets up middleware, routers, and external service integrations.

### Application Startup Sequence

```mermaid
sequenceDiagram
    participant Main as MainApp.__init__
    participant Env as load_dotenv
    participant Sentry as setup_sentry
    participant Phoenix as setup_phoenix_tracing
    participant CORS as setup_cors
    participant Logging as setup_logging_middleware
    participant Routers as include_routers
    participant Startup as startup_event
    participant DB as initialize_database
    participant Data as setup_data
    participant Prompts as SystemPromptSetup
    
    Main->>Env: Load .env file
    Main->>Sentry: Initialize Sentry SDK (production only)
    Main->>Phoenix: Initialize Phoenix tracing
    Main->>CORS: Add CORSMiddleware
    Note over CORS: Origins from CORS_ALLOWED_ORIGINS
    Main->>Logging: Add LoggingContextMiddleware
    Main->>Routers: Register 16 API routers
    Note over Routers: auth, user, parsing, conversations<br/>prompts, projects, search, github<br/>agents, providers, tools, usage<br/>potpie_api, secret_manager, media, integrations
    
    Main->>Startup: Register startup_event handler
    Startup->>DB: Base.metadata.create_all(engine)
    Note over DB: Initialize PostgreSQL schema
    Startup->>Data: Setup Firebase or dummy user
    Note over Data: Conditional on isDevelopmentMode
    Startup->>Prompts: initialize_system_prompts()
    Note over Prompts: Load default prompts into DB
```

**Sources:** [app/main.py:46-211](), [app/main.py:147-171]()

### Router Registration

The application registers 16 modular routers during initialization at [app/main.py:147-171](). Each router is prefixed with `/api/v1` (or `/api/v2` for the potpie_api_router):

```python
# Router initialization pattern from main.py
self.app.include_router(auth_router, prefix="/api/v1", tags=["Auth"])
self.app.include_router(conversations_router, prefix="/api/v1", tags=["Conversations"])
self.app.include_router(agent_router, prefix="/api/v1", tags=["Agents"])
# ... 13 more routers
```

**Sources:** [app/main.py:147-171]()

---

## Conversation Request Flow

The conversation system implements a sophisticated request flow that supports both synchronous and asynchronous execution, with streaming responses and session resumability.

### Message Posting Flow

```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant Router as ConversationAPI.post_message<br/>conversations_router.py:162
    participant Controller as ConversationController<br/>conversation_controller.py:106
    participant Service as ConversationService.store_message<br/>conversation_service.py:544
    participant History as ChatHistoryService
    participant Media as MediaService
    participant TaskRouter as start_celery_task_and_stream<br/>conversation_routing.py
    participant Celery as execute_message_background
    participant Redis as RedisStreamManager
    
    Client->>Router: POST /conversations/{id}/message/<br/>content, images, node_ids
    Router->>Router: Process images with MediaService
    Note over Router: Uploads to GCS/S3/Azure<br/>Returns attachment_ids
    Router->>Router: Parse node_ids JSON
    Router->>Controller: post_message(conversation_id, MessageRequest)
    Controller->>Service: store_message(message, HUMAN, stream=True)
    Service->>History: add_message_chunk(content, HUMAN)
    Service->>History: flush_message_buffer()
    Note over History: Write to PostgreSQL messages table
    Service->>Media: update_message_attachments(message_id, attachment_ids)
    
    alt stream=True
        Service->>TaskRouter: Generate run_id, start Celery task
        TaskRouter->>Celery: execute_message_background.delay()
        TaskRouter->>Redis: Set task status to "queued"
        TaskRouter->>Redis: Publish "queued" event
        TaskRouter-->>Client: StreamingResponse(redis_stream_generator)
        Note over Client,Redis: Client consumes SSE stream<br/>from Redis Stream
    else stream=False
        Service->>Service: _generate_and_stream_ai_response()
        Service-->>Client: Single JSON response
    end
```

**Sources:** [app/modules/conversations/conversations_router.py:162-286](), [app/modules/conversations/conversation/conversation_controller.py:106-119](), [app/modules/conversations/conversation/conversation_service.py:544-652]()

### Service Dependency Injection

The `ConversationService` constructor demonstrates the dependency injection pattern used throughout the codebase:

```python
# From conversation_service.py:74-109
def __init__(
    self,
    db: Session,
    user_id: str,
    user_email: str,
    conversation_store: ConversationStore,
    message_store: MessageStore,
    project_service: ProjectService,
    history_manager: ChatHistoryService,
    provider_service: ProviderService,
    tools_service: ToolService,
    promt_service: PromptService,
    agent_service: AgentsService,
    custom_agent_service: CustomAgentService,
    media_service: MediaService,
    session_service: SessionService = None,
    redis_manager: RedisStreamManager = None,
):
```

This pattern ensures testability and clear service boundaries. The `create` classmethod at [app/modules/conversations/conversation/conversation_service.py:126-164]() instantiates all dependencies.

**Sources:** [app/modules/conversations/conversation/conversation_service.py:73-164]()

---

## Streaming and Session Management

The system uses Redis Streams for real-time response streaming and session resumability, enabling clients to reconnect to ongoing operations without data loss.

### Redis Stream Architecture

```mermaid
graph TB
    subgraph ClientLayer["Client Interaction"]
        HTTPRequest["POST /conversations/{id}/message/"]
        SSEConsumer["StreamingResponse Consumer<br/>Server-Sent Events"]
        ResumeRequest["POST /conversations/{id}/resume/{session_id}"]
    end
    
    subgraph APILayer["API Layer"]
        Router["conversations_router.post_message<br/>line 162"]
        ResumeEndpoint["conversations_router.resume_session<br/>line 521"]
        RunIdGen["normalize_run_id()<br/>ensure_unique_run_id()"]
    end
    
    subgraph BackgroundExecution["Background Execution"]
        CeleryTask["execute_message_background<br/>Celery Task"]
        AgentExec["AgentService.execute_stream()"]
        RedisPublish["redis_manager.publish_event()"]
    end
    
    subgraph RedisLayer["Redis Streams"]
        StreamKey["potpie:stream:{conv_id}:{run_id}"]
        StatusKey["potpie:task_status:{conv_id}:{run_id}"]
        TaskIdKey["potpie:task_id:{conv_id}:{run_id}"]
        Cursor["Stream Cursor<br/>0-0, 1234567890-0, etc"]
    end
    
    subgraph SessionMgmt["Session Management"]
        SessionService["SessionService<br/>get_active_session()"]
        StreamTTL["Stream TTL: 1 hour<br/>Configurable via env"]
    end
    
    HTTPRequest --> Router
    Router --> RunIdGen
    Note1["run_id = hash(conv_id + user_id + session_id)"]
    RunIdGen -.->|deterministic| Note1
    Router --> CeleryTask
    Router --> StreamKey
    Router --> SSEConsumer
    
    CeleryTask --> AgentExec
    AgentExec --> RedisPublish
    RedisPublish --> StreamKey
    RedisPublish --> StatusKey
    CeleryTask --> TaskIdKey
    
    SSEConsumer --> Cursor
    Cursor --> StreamKey
    
    ResumeRequest --> ResumeEndpoint
    ResumeEndpoint --> SessionService
    SessionService --> StreamKey
    SessionService --> StatusKey
    ResumeEndpoint --> SSEConsumer
    
    StreamKey -.->|expires after| StreamTTL
```

**Sources:** [app/modules/conversations/conversations_router.py:162-286](), [app/modules/conversations/utils/conversation_routing.py]()

### Session Lifecycle States

| State | Description | Redis Key | API Endpoint |
|-------|-------------|-----------|--------------|
| `queued` | Task submitted to Celery, not yet started | `potpie:task_status:{conv_id}:{run_id}` | N/A |
| `active` | Agent execution in progress | `potpie:stream:{conv_id}:{run_id}` | `/conversations/{id}/active-session` |
| `completed` | All events published, stream closed | Stream exists with `completed` event | N/A |
| `failed` | Error occurred during execution | Stream exists with `error` event | N/A |
| `expired` | Stream TTL reached (default 1 hour) | Keys deleted from Redis | Returns 404 on resume |

**Sources:** [app/modules/conversations/conversations_router.py:461-518](), [app/modules/conversations/conversation/conversation_schema.py:69-93]()

---

## Service Layer Composition

Services follow a consistent composition pattern where higher-level services depend on lower-level services, avoiding circular dependencies.

### Service Dependency Graph

```mermaid
graph TD
    ConversationController["ConversationController<br/>conversation_controller.py:33"]
    ConversationService["ConversationService<br/>conversation_service.py:73"]
    ConversationStore["ConversationStore"]
    MessageStore["MessageStore"]
    ProjectService["ProjectService<br/>conversation_service.py:97"]
    ChatHistoryService["ChatHistoryService<br/>conversation_service.py:98"]
    ProviderService["ProviderService<br/>conversation_service.py:99"]
    ToolService["ToolService<br/>conversation_service.py:100"]
    PromptService["PromptService<br/>conversation_service.py:101"]
    AgentsService["AgentsService<br/>conversation_service.py:102"]
    CustomAgentService["CustomAgentService<br/>conversation_service.py:103"]
    MediaService["MediaService<br/>conversation_service.py:104"]
    SessionService["SessionService<br/>conversation_service.py:106"]
    RedisStreamManager["RedisStreamManager<br/>conversation_service.py:107"]
    
    ConversationController --> ConversationService
    ConversationController --> ConversationStore
    ConversationController --> MessageStore
    
    ConversationService --> ConversationStore
    ConversationService --> MessageStore
    ConversationService --> ProjectService
    ConversationService --> ChatHistoryService
    ConversationService --> ProviderService
    ConversationService --> ToolService
    ConversationService --> PromptService
    ConversationService --> AgentsService
    ConversationService --> CustomAgentService
    ConversationService --> MediaService
    ConversationService --> SessionService
    ConversationService --> RedisStreamManager
    
    AgentsService --> ProviderService
    AgentsService --> PromptService
    AgentsService --> ToolService
    
    CustomAgentService --> ProviderService
    CustomAgentService --> ToolService
```

**Sources:** [app/modules/conversations/conversation/conversation_controller.py:33-51](), [app/modules/conversations/conversation/conversation_service.py:73-164]()

The `ConversationService.create()` classmethod at [app/modules/conversations/conversation/conversation_service.py:126-164]() demonstrates the factory pattern for dependency instantiation:

```python
@classmethod
def create(cls, conversation_store, message_store, db, user_id, user_email):
    project_service = ProjectService(db)
    history_manager = ChatHistoryService(db)
    provider_service = ProviderService(db, user_id)
    tool_service = ToolService(db, user_id)
    prompt_service = PromptService(db)
    agent_service = AgentsService(db, provider_service, prompt_service, tool_service)
    custom_agent_service = CustomAgentService(db, provider_service, tool_service)
    media_service = MediaService(db)
    session_service = SessionService()
    redis_manager = RedisStreamManager()
    
    return cls(db, user_id, user_email, conversation_store, message_store, 
               project_service, history_manager, provider_service, tool_service,
               prompt_service, agent_service, custom_agent_service, 
               media_service, session_service, redis_manager)
```

**Sources:** [app/modules/conversations/conversation/conversation_service.py:126-164]()

---

## Data Persistence Architecture

The system implements polyglot persistence with four specialized data stores, each optimized for specific access patterns.

### Database Usage by Service

```mermaid
graph LR
    subgraph Services["Service Layer"]
        ConvSvc["ConversationService"]
        AgentSvc["AgentsService"]
        ProjectSvc["ProjectService"]
        AuthSvc["UnifiedAuthService"]
        ParseSvc["Code Graph Services"]
    end
    
    subgraph PostgreSQL["PostgreSQL<br/>POSTGRES_SERVER"]
        Users["users table"]
        Conversations["conversations table"]
        Messages["messages table"]
        Projects["projects table"]
        CustomAgents["custom_agents table"]
        Prompts["prompts table"]
        AuthProviders["user_auth_providers table"]
    end
    
    subgraph Neo4j["Neo4j<br/>NEO4J_URI"]
        CodeNodes["Code Nodes<br/>FILE/CLASS/FUNCTION"]
        Relationships["Relationships<br/>CALLS/REFERENCES"]
        Embeddings["Vector Embeddings<br/>384-dimensional"]
    end
    
    subgraph Redis["Redis<br/>REDISHOST:REDISPORT"]
        Streams["Redis Streams<br/>potpie:stream:*"]
        TaskStatus["Task Status<br/>potpie:task_status:*"]
        CeleryBroker["Celery Broker<br/>BROKER_URL"]
    end
    
    subgraph Firebase["Firebase<br/>FIREBASE_SERVICE_ACCOUNT"]
        FirebaseAuth["Firebase Authentication"]
        Firestore["Firestore<br/>Onboarding Data"]
    end
    
    ConvSvc --> Conversations
    ConvSvc --> Messages
    ConvSvc --> Streams
    ConvSvc --> TaskStatus
    
    AgentSvc --> CustomAgents
    AgentSvc --> Prompts
    
    ProjectSvc --> Projects
    ProjectSvc --> CodeNodes
    ProjectSvc --> Relationships
    ProjectSvc --> Embeddings
    
    AuthSvc --> Users
    AuthSvc --> AuthProviders
    AuthSvc --> FirebaseAuth
    AuthSvc --> Firestore
    
    ParseSvc --> CodeNodes
    ParseSvc --> Relationships
    ParseSvc --> CeleryBroker
```

**Sources:** [.env.template:5-11](), [app/modules/conversations/conversation/conversation_service.py:92-108]()

### Database Connection Configuration

Database connections are configured via environment variables defined in [.env.template:5-11]():

| Variable | Purpose | Example |
|----------|---------|---------|
| `POSTGRES_SERVER` | PostgreSQL connection string | `postgresql://postgres:pass@localhost:5432/momentum` |
| `NEO4J_URI` | Neo4j Bolt protocol endpoint | `bolt://127.0.0.1:7687` |
| `NEO4J_USERNAME` | Neo4j authentication username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j authentication password | `mysecretpassword` |
| `REDISHOST` | Redis server hostname | `127.0.0.1` |
| `REDISPORT` | Redis server port | `6379` |
| `BROKER_URL` | Celery broker (Redis) URL | `redis://127.0.0.1:6379/0` |

**Sources:** [.env.template:5-11]()

---

## Asynchronous Task Processing

Long-running operations are handled asynchronously using Celery with Redis as the message broker, preventing API request timeouts.

### Background Task Pattern

```mermaid
sequenceDiagram
    participant API as FastAPI Endpoint
    participant Router as conversations_router
    participant Celery as Celery Worker
    participant Task as execute_message_background
    participant Redis as RedisStreamManager
    participant Agent as AgentsService
    participant Client as HTTP Client (SSE)
    
    API->>Router: POST /conversations/{id}/message/
    Router->>Router: Generate run_id (deterministic hash)
    Router->>Redis: Set task_status = "queued"
    Router->>Redis: Publish "queued" event
    Router->>Celery: execute_message_background.delay()
    Note over Celery: Task ID stored in Redis
    Router-->>API: 202 Accepted + StreamingResponse
    API-->>Client: Begin SSE stream
    
    Celery->>Task: Background execution starts
    Task->>Redis: Set task_status = "active"
    Task->>Redis: Publish "started" event
    Task->>Agent: execute_stream(query, context)
    
    loop Agent Execution
        Agent->>Redis: publish_event("chunk", data)
        Redis-->>Client: SSE: data: {"message": "..."}<br/>
        Agent->>Redis: publish_event("citation", data)
        Redis-->>Client: SSE: data: {"citations": [...]}<br/>
        Agent->>Redis: publish_event("tool_call", data)
        Redis-->>Client: SSE: data: {"tool_calls": [...]}<br/>
    end
    
    Task->>Redis: Set task_status = "completed"
    Task->>Redis: Publish "completed" event
    Redis-->>Client: SSE: data: {"status": "completed"}<br/>
    Client->>Client: Close SSE connection
```

**Sources:** [app/modules/conversations/conversations_router.py:162-286](), [app/celery/tasks/agent_tasks.py]()

### Celery Configuration

Celery is configured to use Redis as both the message broker and result backend. The configuration is set via environment variables:

- `BROKER_URL`: Redis URL for message queue (default: `redis://127.0.0.1:6379/0`)
- `CELERY_QUEUE_NAME`: Queue name for task routing (default: `dev`)

**Sources:** [.env.template:11-12]()

---

## Technology Stack Summary

The following table summarizes the core technologies and their purposes in the system:

| Technology | Purpose | Configuration | Key Files |
|------------|---------|---------------|-----------|
| **FastAPI** | Web framework, API gateway | Port 8000, Uvicorn ASGI server | [app/main.py]() |
| **SQLAlchemy** | ORM for PostgreSQL | Async and sync sessions | [app/core/database.py]() |
| **PostgreSQL** | Relational data storage | `POSTGRES_SERVER` env var | [.env.template:5]() |
| **Neo4j** | Code knowledge graph | Bolt driver, `NEO4J_URI` env var | [.env.template:6-8]() |
| **Redis** | Caching, streaming, Celery broker | `REDISHOST`, `REDISPORT` env vars | [.env.template:9-10]() |
| **Celery** | Asynchronous task queue | Redis broker, `CELERY_QUEUE_NAME` | [.env.template:11-12]() |
| **Firebase** | Authentication, Firestore | `FIREBASE_SERVICE_ACCOUNT` | [.env.template:60]() |
| **LiteLLM** | LLM provider abstraction | Various `*_API_KEY` env vars | [requirements.txt:125]() |
| **Pydantic** | Data validation, serialization | v2.x for structured outputs | [requirements.txt:194]() |
| **Tree-sitter** | Code parsing, AST generation | Language-specific parsers | [requirements.txt:253-257]() |
| **Sentence Transformers** | Embedding generation | Local model inference | [requirements.txt:230]() |
| **Sentry** | Error tracking (production) | `SENTRY_DSN` env var | [app/main.py:64-87]() |
| **Phoenix** | OpenTelemetry tracing | `PHOENIX_COLLECTOR_ENDPOINT` | [.env.template:75-81]() |

**Sources:** [requirements.txt:1-279](), [.env.template:1-116](), [app/main.py:1-217]()

---

## Development vs Production Modes

The system supports two operational modes controlled by the `isDevelopmentMode` environment variable at [.env.template:1]().

### Mode Comparison

| Feature | Development Mode (`enabled`) | Production Mode |
|---------|----------------------------|-----------------|
| **Authentication** | Mock user, no Firebase | Firebase Authentication required |
| **User Setup** | Dummy user auto-created | Real user registration |
| **Firebase** | Skipped | Required (`FIREBASE_SERVICE_ACCOUNT`) |
| **Secret Management** | Local environment variables | Google Cloud Secret Manager |
| **Sentry** | Disabled | Enabled with `SENTRY_DSN` |
| **CORS** | `http://localhost:3000` | Configurable via `CORS_ALLOWED_ORIGINS` |
| **Startup Validation** | Lax validation | Strict (exits on misconfiguration) |

**Development mode initialization** at [app/main.py:132-139]():
```python
if os.getenv("isDevelopmentMode") == "enabled":
    logger.info("Development mode enabled. Skipping Firebase setup.")
    db = SessionLocal()
    user_service = UserService(db)
    user_service.setup_dummy_user()  # Creates default test user
    db.close()
```

**Production mode validation** at [app/main.py:49-56]():
```python
if (os.getenv("isDevelopmentMode") == "enabled" 
    and os.getenv("ENV") != "development"):
    logger.error("Development mode enabled but ENV is not set to development. Exiting.")
    exit(1)
```

**Sources:** [app/main.py:49-56](), [app/main.py:132-141](), [.env.template:1-2]()

---

## Middleware Stack

The FastAPI application uses a middleware stack for cross-cutting concerns. Middleware is added in reverse order of execution (last added executes first).

### Middleware Execution Order

```mermaid
graph TD
    Request["HTTP Request"]
    CORS["CORSMiddleware<br/>app/main.py:107-113"]
    Logging["LoggingContextMiddleware<br/>app/main.py:128"]
    Router["Route Handler"]
    Response["HTTP Response"]
    
    Request --> CORS
    CORS --> Logging
    Logging --> Router
    Router --> Logging
    Logging --> CORS
    CORS --> Response
    
    Note1["1. CORS: Validates origin, adds headers"]
    Note2["2. Logging: Injects request_id, user_id context"]
    Note3["3. Route: Executes business logic"]
    
    CORS -.-> Note1
    Logging -.-> Note2
    Router -.-> Note3
```

**Middleware registration** at [app/main.py:107-129]():

1. **CORSMiddleware** ([app/main.py:107-114]()): Handles cross-origin requests
   - Origins from `CORS_ALLOWED_ORIGINS` (comma-separated)
   - Allows all methods and headers
   - Credentials enabled

2. **LoggingContextMiddleware** ([app/main.py:128]()): Injects structured logging context
   - `request_id`: UUID for request tracing
   - `path`: API endpoint path
   - `user_id`: Authenticated user (if available)

**Sources:** [app/main.py:101-129](), [app/modules/utils/logging_middleware.py]()

---

## Router-to-Service Mapping

The following table shows the complete mapping of API routers to their service implementations:

| Router | Prefix | Module Path | Primary Service | Tags |
|--------|--------|-------------|-----------------|------|
| `auth_router` | `/api/v1` | `app/modules/auth/auth_router.py` | `UnifiedAuthService` | Auth |
| `user_router` | `/api/v1` | `app/modules/users/user_router.py` | `UserService` | User |
| `parsing_router` | `/api/v1` | `app/modules/parsing/graph_construction/parsing_router.py` | Parsing services | Parsing |
| `conversations_router` | `/api/v1` | `app/modules/conversations/conversations_router.py` | `ConversationService` | Conversations |
| `prompt_router` | `/api/v1` | `app/modules/intelligence/prompts/prompt_router.py` | `PromptService` | Prompts |
| `projects_router` | `/api/v1` | `app/modules/projects/projects_router.py` | `ProjectService` | Projects |
| `search_router` | `/api/v1` | `app/modules/search/search_router.py` | `SearchService` | Search |
| `github_router` | `/api/v1` | `app/modules/code_provider/github/github_router.py` | GitHub integration | Github |
| `agent_router` | `/api/v1` | `app/modules/intelligence/agents/agents_router.py` | `AgentsService` | Agents |
| `provider_router` | `/api/v1` | `app/modules/intelligence/provider/provider_router.py` | `ProviderService` | Providers |
| `tool_router` | `/api/v1` | `app/modules/intelligence/tools/tool_router.py` | `ToolService` | Tools |
| `usage_router` | `/api/v1/usage` | `app/modules/usage/usage_router.py` | `UsageService` | Usage |
| `potpie_api_router` | `/api/v2` | `app/api/router.py` | Various | Potpie API |
| `secret_manager_router` | `/api/v1` | `app/modules/key_management/secret_manager.py` | Secret management | Secret Manager |
| `media_router` | `/api/v1` | `app/modules/media/media_router.py` | `MediaService` | Media |
| `integrations_router` | `/api/v1` | `app/modules/integrations/integrations_router.py` | Integration services | Integrations |

**Sources:** [app/main.py:147-171]()