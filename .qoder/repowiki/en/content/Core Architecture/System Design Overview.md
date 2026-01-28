# System Design Overview

<cite>
**Referenced Files in This Document**
- [app/main.py](file://app/main.py)
- [app/api/router.py](file://app/api/router.py)
- [app/modules/utils/APIRouter.py](file://app/modules/utils/APIRouter.py)
- [app/core/database.py](file://app/core/database.py)
- [app/core/base_model.py](file://app/core/base_model.py)
- [app/core/config_provider.py](file://app/core/config_provider.py)
- [app/celery/celery_app.py](file://app/celery/celery_app.py)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py)
- [app/modules/intelligence/agents/agents_service.py](file://app/modules/intelligence/agents/agents_service.py)
- [app/modules/parsing/graph_construction/parsing_service.py](file://app/modules/parsing/graph_construction/parsing_service.py)
- [app/modules/auth/auth_service.py](file://app/modules/auth/auth_service.py)
- [app/modules/utils/logging_middleware.py](file://app/modules/utils/logging_middleware.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document presents Potpie’s microservices-based backend architecture centered on a FastAPI application. The system emphasizes modular routers, layered architecture (presentation, business logic, data access), dependency injection, and robust configuration management. It leverages Celery for asynchronous task processing, Redis for streaming and caching, and integrates with Neo4j for knowledge graph operations. The design prioritizes maintainability, scalability, and observability through structured routing, centralized configuration, and middleware-driven logging.

## Project Structure
Potpie organizes functionality by feature areas under app/modules, each containing routers, controllers, services, stores, and schemas. A central FastAPI application composes modular routers and initializes infrastructure on startup. Supporting modules manage database engines, configuration providers, and logging middleware.

```mermaid
graph TB
subgraph "FastAPI Application"
MAIN["app/main.py<br/>MainApp"]
API_ROUTER["app/api/router.py<br/>API v2 Router"]
end
subgraph "Feature Modules"
AUTH["app/modules/auth/*<br/>Auth Router/Service"]
CONV["app/modules/conversations/*<br/>Conversations Router/Controller/Service"]
INT["app/modules/intelligence/*<br/>Agents/Prompts/Tools/Provider"]
PARS["app/modules/parsing/*<br/>Graph Construction/Inference"]
UTILS["app/modules/utils/*<br/>APIRouter, Logging Middleware"]
end
subgraph "Core Infrastructure"
DB["app/core/database.py<br/>SQL & Async Engines"]
BASE["app/core/base_model.py<br/>Declarative Base"]
CFG["app/core/config_provider.py<br/>Config Provider"]
CELERY["app/celery/celery_app.py<br/>Celery Worker"]
end
MAIN --> API_ROUTER
MAIN --> AUTH
MAIN --> CONV
MAIN --> INT
MAIN --> PARS
MAIN --> UTILS
API_ROUTER --> CONV
API_ROUTER --> INT
API_ROUTER --> PARS
CONV --> DB
INT --> DB
PARS --> DB
DB --> BASE
MAIN --> DB
MAIN --> CFG
MAIN --> CELERY
```

**Diagram sources**
- [app/main.py](file://app/main.py#L147-L171)
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/core/database.py](file://app/core/database.py#L13-L52)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

**Section sources**
- [app/main.py](file://app/main.py#L147-L171)
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/core/database.py](file://app/core/database.py#L13-L52)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

## Core Components
- FastAPI Application Bootstrap: Initializes environment, Sentry, Phoenix tracing, CORS, logging middleware, database, and registers modular routers.
- Modular Routers: Each feature area defines its own router with APIRoute decorator extension for trailing slash normalization.
- Controllers and Services: Presentation controllers orchestrate service layer operations; services encapsulate business logic and dependencies.
- Data Access: SQLAlchemy for synchronous ORM and asyncpg for asynchronous sessions; dependency injection via get_db/get_async_db.
- Configuration Management: Centralized provider for environment-backed settings and object storage strategies.
- Asynchronous Task Execution: Celery workers handle long-running tasks with Redis transport and task routing.

**Section sources**
- [app/main.py](file://app/main.py#L46-L211)
- [app/modules/utils/APIRouter.py](file://app/modules/utils/APIRouter.py#L7-L27)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L73-L164)
- [app/core/database.py](file://app/core/database.py#L100-L116)
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

## Architecture Overview
The system follows a layered architecture:
- Presentation Layer: FastAPI routers and controllers expose endpoints and coordinate service calls.
- Business Logic Layer: Services encapsulate domain logic, orchestrate tools/providers, and manage cross-cutting concerns.
- Data Access Layer: Stores and models abstract persistence; SQLAlchemy and async sessions provide transactional boundaries.

```mermaid
graph TB
CLIENT["Client"]
FASTAPI["FastAPI App<br/>app/main.py"]
ROUTER["Routers<br/>app/api/router.py<br/>Feature routers"]
CTRL["Controllers<br/>ConversationController"]
SVC["Services<br/>ConversationService<br/>AgentsService<br/>ParsingService"]
STORES["Stores & Models<br/>ConversationStore<br/>MessageStore<br/>ORM Models"]
DB["PostgreSQL<br/>SQLAlchemy"]
REDIS["Redis<br/>Streaming & Queues"]
NEO4J["Neo4j<br/>Knowledge Graph"]
CLIENT --> FASTAPI
FASTAPI --> ROUTER
ROUTER --> CTRL
CTRL --> SVC
SVC --> STORES
STORES --> DB
SVC --> REDIS
SVC --> NEO4J
```

**Diagram sources**
- [app/main.py](file://app/main.py#L147-L171)
- [app/api/router.py](file://app/api/router.py#L97-L318)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L73-L164)
- [app/modules/intelligence/agents/agents_service.py](file://app/modules/intelligence/agents/agents_service.py#L47-L66)
- [app/modules/parsing/graph_construction/parsing_service.py](file://app/modules/parsing/graph_construction/parsing_service.py#L33-L60)
- [app/core/database.py](file://app/core/database.py#L13-L52)

## Detailed Component Analysis

### FastAPI Application Bootstrapping
- Environment and Observability: Loads .env, sets tokenization behavior, initializes Sentry and Phoenix tracing conditionally.
- Middleware: Adds CORS and a LoggingContextMiddleware that injects request_id, path, and user_id into logs.
- Database Initialization: Creates tables on startup and seeds development data or initializes Firebase in production.
- Router Registration: Includes modular routers under /api/v1 and /api/v2 prefixes with tags for grouping.
- Health Endpoint: Provides version information derived from Git.

```mermaid
sequenceDiagram
participant Client as "Client"
participant Main as "MainApp"
participant App as "FastAPI App"
participant DB as "Database"
participant Data as "Data Setup"
Client->>Main : Instantiate MainApp()
Main->>Main : load_dotenv()<br/>setup_sentry()<br/>setup_phoenix_tracing()
Main->>App : FastAPI()
Main->>App : setup_cors()<br/>setup_logging_middleware()
Main->>App : include_routers()
Main->>App : add_health_check()
Client->>App : Startup event
App->>DB : initialize_database()
App->>Data : setup_data()
Data-->>App : complete
App-->>Client : Ready
```

**Diagram sources**
- [app/main.py](file://app/main.py#L46-L211)

**Section sources**
- [app/main.py](file://app/main.py#L46-L211)

### Modular Router-Based Organization
- API v2 Router: Centralized endpoint definitions for conversations, parsing, search, integrations, and more, with API key authentication and usage checks.
- Feature Routers: Each module defines its own router (e.g., auth, conversations, intelligence, parsing) and is included by MainApp.
- APIRoute Extension: Custom APIRouter normalizes trailing slashes to ensure consistent endpoint shapes.

```mermaid
graph LR
API["API v2 Router<br/>app/api/router.py"]
AUTH_R["Auth Router"]
CONV_R["Conversations Router"]
INT_R["Intelligence Routers"]
PARS_R["Parsing Router"]
OTHER["Other Feature Routers"]
API --> AUTH_R
API --> CONV_R
API --> INT_R
API --> PARS_R
API --> OTHER
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/modules/utils/APIRouter.py](file://app/modules/utils/APIRouter.py#L7-L27)
- [app/main.py](file://app/main.py#L147-L171)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/modules/utils/APIRouter.py](file://app/modules/utils/APIRouter.py#L7-L27)
- [app/main.py](file://app/main.py#L147-L171)

### Layered Architecture and Separation of Concerns
- Presentation: Controllers translate HTTP requests into domain actions and delegate to services.
- Business Logic: Services encapsulate workflows, validate inputs, and coordinate tools/providers.
- Data Access: Stores and models abstract persistence; dependency injection supplies sessions.

```mermaid
classDiagram
class ConversationController {
+create_conversation()
+post_message()
+regenerate_last_message()
}
class ConversationService {
+create_conversation()
+store_message()
+regenerate_last_message()
}
class AgentsService {
+execute()
+list_available_agents()
}
class ParsingService {
+parse_directory()
+analyze_directory()
}
class ConversationStore
class MessageStore
class Base
ConversationController --> ConversationService : "orchestrates"
ConversationService --> ConversationStore : "uses"
ConversationService --> MessageStore : "uses"
ConversationService --> AgentsService : "uses"
ConversationService --> ParsingService : "uses"
ConversationStore --> Base : "models"
MessageStore --> Base : "models"
```

**Diagram sources**
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L73-L164)
- [app/modules/intelligence/agents/agents_service.py](file://app/modules/intelligence/agents/agents_service.py#L47-L66)
- [app/modules/parsing/graph_construction/parsing_service.py](file://app/modules/parsing/graph_construction/parsing_service.py#L33-L60)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)

**Section sources**
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L73-L164)
- [app/modules/intelligence/agents/agents_service.py](file://app/modules/intelligence/agents/agents_service.py#L47-L66)
- [app/modules/parsing/graph_construction/parsing_service.py](file://app/modules/parsing/graph_construction/parsing_service.py#L33-L60)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)

### Dependency Injection Patterns
- Database Sessions: get_db for synchronous and get_async_db for asynchronous routes; dependency injection resolves sessions per request.
- Service Composition: Controllers construct services with required dependencies (stores, providers, services).
- Configuration: ConfigProvider centralizes environment-backed settings and strategies.

```mermaid
flowchart TD
Start(["Route Handler"]) --> InjectDB["Depends(get_db/get_async_db)"]
InjectDB --> BuildController["Instantiate Controller with db/async_db"]
BuildController --> BuildService["Service.create(...) with dependencies"]
BuildService --> UseStores["Use ConversationStore/MessageStore"]
UseStores --> UseModels["ORM Models via Base"]
UseModels --> End(["Response"])
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L103-L105)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L126-L164)
- [app/core/database.py](file://app/core/database.py#L100-L116)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L103-L105)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L33-L51)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L126-L164)
- [app/core/database.py](file://app/core/database.py#L100-L116)
- [app/core/base_model.py](file://app/core/base_model.py#L8-L16)

### Configuration Management
- Environment Variables: Loaded via dotenv; used to configure database URLs, Redis, Neo4j, object storage, and feature flags.
- Strategy Pattern: Object storage provider selection uses pluggable strategies with readiness checks.
- Global Overrides: Neo4j configuration can be overridden globally for library usage.

```mermaid
flowchart TD
Env["Load .env"] --> Config["ConfigProvider"]
Config --> DBURL["POSTGRES_SERVER"]
Config --> Redis["Redis URL"]
Config --> Neo4j["Neo4j Config"]
Config --> Storage["Object Storage Strategy"]
Storage --> Ready{"Is Ready?"}
Ready --> |Yes| UseStorage["Use Provider"]
Ready --> |No| AutoDetect["Auto-detect Provider"]
```

**Diagram sources**
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)

**Section sources**
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)

### Asynchronous Task Execution and Streaming
- Celery Workers: Redis transport, task routing, and worker lifecycle management; LiteLLM logging synchronization to avoid async handler issues.
- Streaming: Redis streams manage conversation streaming; controllers and services integrate with Celery tasks for both streaming and non-streaming responses.

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "API Router"
participant Controller as "ConversationController"
participant Service as "ConversationService"
participant Celery as "Celery Worker"
participant Redis as "Redis Stream"
Client->>API : POST /api/v2/conversations/{id}/message/
API->>Controller : post_message(...)
Controller->>Service : store_message(..., stream)
alt Streaming
Service->>Celery : start_celery_task_and_stream(...)
Celery->>Redis : Publish chunks
Redis-->>Client : SSE-like stream
else Non-streaming
Service->>Celery : start_celery_task_and_wait(...)
Celery-->>Client : Complete response
end
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L150-L217)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L106-L131)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L544-L652)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L150-L217)
- [app/modules/conversations/conversation/conversation_controller.py](file://app/modules/conversations/conversation/conversation_controller.py#L106-L131)
- [app/modules/conversations/conversation/conversation_service.py](file://app/modules/conversations/conversation/conversation_service.py#L544-L652)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

### Authentication and Authorization
- API Key Validation: API v2 router validates X-API-Key and optionally INTERNAL_ADMIN_SECRET for administrative actions.
- Firebase Auth: Feature routers may rely on AuthService.check_auth to populate request.state.user for downstream authorization.
- Logging Context: LoggingContextMiddleware reads request.state.user to enrich logs with user_id.

```mermaid
flowchart TD
Req["Incoming Request"] --> APIKey["get_api_key_user()"]
APIKey --> |Valid| UserCtx["User Context"]
APIKey --> |Invalid| Error["HTTP 401"]
UserCtx --> Controller["Controller"]
Controller --> Service["Service"]
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L56-L87)
- [app/modules/auth/auth_service.py](file://app/modules/auth/auth_service.py#L48-L104)
- [app/modules/utils/logging_middleware.py](file://app/modules/utils/logging_middleware.py#L33-L59)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L56-L87)
- [app/modules/auth/auth_service.py](file://app/modules/auth/auth_service.py#L48-L104)
- [app/modules/utils/logging_middleware.py](file://app/modules/utils/logging_middleware.py#L33-L59)

## Dependency Analysis
- Coupling: Controllers depend on services; services depend on stores/providers; stores depend on ORM models.
- Cohesion: Each module encapsulates a bounded context (auth, conversations, intelligence, parsing).
- External Dependencies: PostgreSQL, Redis, Neo4j, Sentry, Phoenix, Celery, and LiteLLM.

```mermaid
graph TB
MAIN["app/main.py"]
API["app/api/router.py"]
AUTH["app/modules/auth/*"]
CONV["app/modules/conversations/*"]
INT["app/modules/intelligence/*"]
PARS["app/modules/parsing/*"]
DB["app/core/database.py"]
CFG["app/core/config_provider.py"]
CELERY["app/celery/celery_app.py"]
MAIN --> API
MAIN --> AUTH
MAIN --> CONV
MAIN --> INT
MAIN --> PARS
API --> CONV
API --> INT
API --> PARS
CONV --> DB
INT --> DB
PARS --> DB
MAIN --> DB
MAIN --> CFG
MAIN --> CELERY
```

**Diagram sources**
- [app/main.py](file://app/main.py#L147-L171)
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/core/database.py](file://app/core/database.py#L13-L52)
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

**Section sources**
- [app/main.py](file://app/main.py#L147-L171)
- [app/api/router.py](file://app/api/router.py#L48-L318)
- [app/core/database.py](file://app/core/database.py#L13-L52)
- [app/core/config_provider.py](file://app/core/config_provider.py#L19-L246)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L129)

## Performance Considerations
- Database Pooling: SQLAlchemy engine configured with pool_size, max_overflow, pool_timeout, and pool_recycle; async engine optimized for asyncpg with NullPool for Celery tasks.
- Async Sessions: AsyncSessionLocal reduces overhead for async routes; Celery workers use fresh connections to avoid Future binding issues.
- Redis Streaming: TTL and max length controls for streams; task routing optimizes worker distribution.
- LiteLLM Logging: Synchronous logging configuration in Celery workers to prevent async handler pitfalls.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Health Checks: Use /health to confirm application status and version.
- Logging Context: Ensure LoggingContextMiddleware is active to include request_id and user_id in logs.
- Database Connectivity: Verify POSTGRES_SERVER and pool settings; check echo flag for diagnostics.
- Redis Connectivity: Confirm Redis URL construction and ping results; mask credentials in logs.
- Sentry/Phoenix: Validate DSN and integrations; ensure environment-specific initialization.

**Section sources**
- [app/main.py](file://app/main.py#L173-L183)
- [app/modules/utils/logging_middleware.py](file://app/modules/utils/logging_middleware.py#L20-L59)
- [app/core/database.py](file://app/core/database.py#L13-L52)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L37-L78)

## Conclusion
Potpie’s backend leverages FastAPI’s performance and automatic documentation capabilities alongside a modular, layered architecture. The design separates presentation, business logic, and data access, enabling maintainability and scalability. Centralized configuration, dependency injection, and Celery-powered asynchronous processing form a robust foundation for microservices-style development across feature domains.