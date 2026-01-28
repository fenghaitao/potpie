# Core Architecture

<cite>
**Referenced Files in This Document**
- [app/main.py](file://app/main.py)
- [app/api/router.py](file://app/api/router.py)
- [app/celery/__init__.py](file://app/celery/__init__.py)
- [app/celery/celery_app.py](file://app/celery/celery_app.py)
- [app/celery/worker.py](file://app/celery/worker.py)
- [app/core/database.py](file://app/core/database.py)
- [app/core/base_model.py](file://app/core/base_model.py)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py)
- [app/modules/auth/unified_auth_service.py](file://app/modules/auth/unified_auth_service.py)
- [app/core/config_provider.py](file://app/core/config_provider.py)
- [app/modules/intelligence/tracing/phoenix_tracer.py](file://app/modules/intelligence/tracing/phoenix_tracer.py)
- [docker-compose.yaml](file://docker-compose.yaml)
- [deployment/prod/mom-api/api.Dockerfile](file://deployment/prod/mom-api/api.Dockerfile)
- [deployment/prod/celery/celery.Dockerfile](file://deployment/prod/celery/celery.Dockerfile)
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
10. [Appendices](#appendices)

## Introduction
This document describes Potpie’s core system design with a focus on its microservices-based backend architecture. The system centers around a FastAPI application that orchestrates modular services, integrates a background job system powered by Celery, and manages persistence and streaming through PostgreSQL, Neo4j, and Redis. Cross-cutting concerns include authentication and authorization, monitoring, error handling, and observability. The deployment topology separates API and worker services, enabling scalable and maintainable operations.

## Project Structure
The repository follows a layered, feature-based organization:
- Application entrypoint initializes FastAPI, middleware, routers, and startup routines.
- Modular feature areas under app/modules encapsulate domain capabilities (authentication, conversations, intelligence, parsing, etc.).
- Background processing is implemented via Celery with dedicated queues and task registration.
- Data access uses SQLAlchemy ORM with both synchronous and asynchronous engines.
- Streaming and real-time updates leverage Redis streams keyed by conversation and run identifiers.
- Infrastructure is provisioned via Docker Compose for PostgreSQL, Neo4j, and Redis.

```mermaid
graph TB
subgraph "API Layer"
MAIN["FastAPI MainApp<br/>app/main.py"]
ROUTER["API Routers<br/>app/api/router.py"]
end
subgraph "Service Layer"
AUTH["Unified Auth Service<br/>app/modules/auth/unified_auth_service.py"]
CONV_ROUTING["Conversation Routing & Streaming<br/>app/modules/conversations/utils/conversation_routing.py"]
REDIS["Redis Stream Manager<br/>app/modules/conversations/utils/redis_streaming.py"]
CONFIG["Config Provider<br/>app/core/config_provider.py"]
end
subgraph "Background Processing"
CELERY_APP["Celery App & Tasks<br/>app/celery/celery_app.py"]
WORKER["Celery Worker<br/>app/celery/worker.py"]
end
subgraph "Data Layer"
DB["SQLAlchemy ORM<br/>app/core/database.py"]
BASE_MODEL["Base Model<br/>app/core/base_model.py"]
end
subgraph "Infrastructure"
PG["PostgreSQL"]
NEO4J["Neo4j"]
REDIS_SVC["Redis"]
end
MAIN --> ROUTER
ROUTER --> AUTH
ROUTER --> CONV_ROUTING
CONV_ROUTING --> REDIS
CONV_ROUTING --> CELERY_APP
CELERY_APP --> WORKER
ROUTER --> DB
DB --> PG
CONFIG --> NEO4J
CONFIG --> REDIS_SVC
```

**Diagram sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/worker.py](file://app/celery/worker.py#L1-L41)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/core/base_model.py](file://app/core/base_model.py#L1-L17)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)

**Section sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)

## Core Components
- FastAPI application bootstrap and middleware pipeline:
  - CORS configuration, logging context middleware, Sentry integration, Phoenix tracing initialization, and health checks.
  - Dynamic router inclusion for modular endpoints.
- Database layer:
  - Synchronous and asynchronous SQLAlchemy engines with connection pooling and session factories.
  - Base declarative model class for ORM.
- Background processing:
  - Celery app configured with Redis broker/backend, task routing, and worker tuning.
  - Worker initialization and task registration.
- Streaming and real-time:
  - Redis-backed streaming for conversation events with TTL and max-length controls.
  - Shared routing utilities to orchestrate Celery tasks and SSE responses.
- Configuration and infrastructure:
  - Centralized configuration provider for Neo4j, Redis, and object storage.
  - Docker Compose services for PostgreSQL, Neo4j, and Redis.

**Section sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/core/base_model.py](file://app/core/base_model.py#L1-L17)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/worker.py](file://app/celery/worker.py#L1-L41)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

## Architecture Overview
The system employs a layered architecture with clear separation of concerns:
- Presentation and orchestration: FastAPI application and routers.
- Service orchestration: Unified authentication, conversation routing, and streaming coordination.
- Background processing: Celery tasks for long-running operations with Redis queues.
- Persistence: PostgreSQL for relational data, Neo4j for graph-based knowledge, and Redis for streaming and ephemeral state.
- Observability: Phoenix tracing for LLM monitoring and Sentry for error reporting.

```mermaid
graph TB
CLIENT["Client"]
API["FastAPI App<br/>app/main.py"]
ROUTERS["Routers<br/>app/api/router.py"]
AUTH["Auth Service<br/>unified_auth_service.py"]
CONV["Conversation Routing<br/>conversation_routing.py"]
STREAM["Redis Streams<br/>redis_streaming.py"]
CELERY["Celery App<br/>celery_app.py"]
WORKER["Celery Worker<br/>worker.py"]
DB["SQLAlchemy Engines<br/>database.py"]
PG["PostgreSQL"]
NEO["Neo4j"]
REDIS["Redis"]
CLIENT --> API
API --> ROUTERS
ROUTERS --> AUTH
ROUTERS --> CONV
CONV --> STREAM
CONV --> CELERY
CELERY --> WORKER
ROUTERS --> DB
DB --> PG
API --> NEO
API --> REDIS
```

**Diagram sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/auth/unified_auth_service.py](file://app/modules/auth/unified_auth_service.py#L1-L800)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/worker.py](file://app/celery/worker.py#L1-L41)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)

## Detailed Component Analysis

### FastAPI Application Bootstrap
- Initializes environment, Sentry, and Phoenix tracing.
- Configures CORS and logging middleware.
- Includes modular routers and adds a health endpoint.
- Startup event creates database tables, seeds data in development, and initializes system prompts.

```mermaid
sequenceDiagram
participant Client as "Client"
participant Main as "MainApp<br/>app/main.py"
participant API as "FastAPI App"
participant Router as "Routers<br/>app/api/router.py"
Client->>Main : Start application
Main->>Main : setup_sentry()<br/>setup_phoenix_tracing()<br/>setup_cors()<br/>setup_logging_middleware()
Main->>API : Create FastAPI app
Main->>API : include_routers()
API->>Router : Register routes
Main->>API : add_health_check()
API-->>Client : Health endpoint available
```

**Diagram sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)

**Section sources**
- [app/main.py](file://app/main.py#L46-L217)

### Database and ORM Layer
- Provides synchronous and asynchronous SQLAlchemy engines with connection pooling and pre-ping.
- Offers session factories for route dependencies and a special async session factory tailored for Celery workers to avoid cross-task Future binding issues.
- Declares a base ORM class for all models.

```mermaid
classDiagram
class Database {
+engine
+async_engine
+SessionLocal
+AsyncSessionLocal
+get_db()
+get_async_db()
+create_celery_async_session()
}
class Base {
+id
+__tablename__()
}
Database --> Base : "declarative base"
```

**Diagram sources**
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/core/base_model.py](file://app/core/base_model.py#L1-L17)

**Section sources**
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/core/base_model.py](file://app/core/base_model.py#L1-L17)

### Background Processing with Celery
- Celery app configured with Redis broker and backend, task routing, and worker tuning (prefetch, late acks, memory limits).
- LiteLLM is configured synchronously in workers to avoid async handler issues.
- Worker initialization registers tasks and starts the worker process.

```mermaid
sequenceDiagram
participant API as "API Router<br/>app/api/router.py"
participant Routing as "Conversation Routing<br/>conversation_routing.py"
participant Redis as "Redis Streams<br/>redis_streaming.py"
participant Celery as "Celery App<br/>celery_app.py"
participant Worker as "Celery Worker<br/>worker.py"
API->>Routing : start_celery_task_and_stream()
Routing->>Redis : set_task_status()<br/>publish_event()
Routing->>Celery : execute_agent_background.delay()
Celery-->>Worker : Dispatch task
Worker-->>Redis : Publish events to stream
API-->>Client : StreamingResponse(text/event-stream)
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L140-L218)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L107-L171)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L66-L129)
- [app/celery/worker.py](file://app/celery/worker.py#L16-L31)

**Section sources**
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/worker.py](file://app/celery/worker.py#L1-L41)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)

### Streaming and Real-Time Updates
- Redis stream manager publishes and consumes conversation events with TTL and max-length constraints.
- Supports reconnection via cursors and cancellation signaling.
- Conversation routing utilities coordinate task initiation, status updates, and SSE responses.

```mermaid
flowchart TD
Start(["Start Request"]) --> Normalize["Normalize run_id"]
Normalize --> Unique{"Ensure unique run_id"}
Unique --> |No| Retry["Append counter"]
Unique --> |Yes| Queue["Publish queued event"]
Queue --> CeleryCall["Start Celery task"]
CeleryCall --> Stream["Publish events to Redis stream"]
Stream --> Consume["Client consumes stream"]
Consume --> End(["End or Error"])
```

**Diagram sources**
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L23-L58)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)

**Section sources**
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)

### Authentication and Authorization
- Unified authentication service supports multiple providers (Firebase, GitHub, SSO) and enforces single-user identity by email.
- Handles provider linking, token encryption/decryption, and audit logging.
- API routers enforce API key-based authentication for internal admin and external clients.

```mermaid
sequenceDiagram
participant Client as "Client"
participant Router as "API Router<br/>app/api/router.py"
participant Auth as "UnifiedAuthService<br/>unified_auth_service.py"
Client->>Router : Request with X-API-Key
Router->>Auth : validate_api_key()
Auth-->>Router : User info or error
Router-->>Client : Authorized request or 401
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L56-L87)
- [app/modules/auth/unified_auth_service.py](file://app/modules/auth/unified_auth_service.py#L1-L800)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L56-L87)
- [app/modules/auth/unified_auth_service.py](file://app/modules/auth/unified_auth_service.py#L1-L800)

### Configuration and Infrastructure
- Config provider centralizes Neo4j, Redis, GitHub, and object storage configuration with auto-detection and overrides.
- Docker Compose provisions PostgreSQL, Neo4j, and Redis with health checks and persistent volumes.
- Production Dockerfiles use uv for dependency installation and Supervisor to manage processes.

```mermaid
graph TB
CP["ConfigProvider<br/>config_provider.py"]
DC["docker-compose.yaml"]
API_DOCKER["API Dockerfile<br/>api.Dockerfile"]
CELERY_DOCKER["Celery Dockerfile<br/>celery.Dockerfile"]
CP --> DC
DC --> PG["PostgreSQL"]
DC --> NEO["Neo4j"]
DC --> REDIS["Redis"]
API_DOCKER --> DC
CELERY_DOCKER --> DC
```

**Diagram sources**
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)
- [deployment/prod/mom-api/api.Dockerfile](file://deployment/prod/mom-api/api.Dockerfile#L1-L46)
- [deployment/prod/celery/celery.Dockerfile](file://deployment/prod/celery/celery.Dockerfile#L1-L46)

**Section sources**
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)
- [deployment/prod/mom-api/api.Dockerfile](file://deployment/prod/mom-api/api.Dockerfile#L1-L46)
- [deployment/prod/celery/celery.Dockerfile](file://deployment/prod/celery/celery.Dockerfile#L1-L46)

## Dependency Analysis
- Application entrypoint depends on routers, database initialization, and startup routines.
- API routers depend on services (auth, conversations, parsing, etc.) and database sessions.
- Celery app depends on Redis and registers tasks for parsing and agent execution.
- Redis stream manager depends on configuration provider for connection details.
- Phoenix tracing is initialized early in the application lifecycle to instrument downstream components.

```mermaid
graph LR
MAIN["app/main.py"] --> ROUTER["app/api/router.py"]
ROUTER --> AUTH["unified_auth_service.py"]
ROUTER --> CONV["conversation_routing.py"]
CONV --> REDIS["redis_streaming.py"]
CONV --> CELERY["celery_app.py"]
CELERY --> WORKER["worker.py"]
ROUTER --> DB["database.py"]
DB --> PG["PostgreSQL"]
MAIN --> PHX["phoenix_tracer.py"]
MAIN --> CFG["config_provider.py"]
CFG --> REDIS
CFG --> NEO["Neo4j"]
```

**Diagram sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/utils/conversation_routing.py](file://app/modules/conversations/utils/conversation_routing.py#L1-L324)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/worker.py](file://app/celery/worker.py#L1-L41)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/intelligence/tracing/phoenix_tracer.py](file://app/modules/intelligence/tracing/phoenix_tracer.py#L71-L278)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

**Section sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)

## Performance Considerations
- Database:
  - Connection pooling and pre-ping reduce stale connections; async sessions minimize contention.
  - Dedicated async session factory for Celery avoids cross-task Future binding issues.
- Background processing:
  - Worker prefetch multiplier and late acknowledgments improve fairness and reliability.
  - Memory limits and restart policies mitigate memory leaks.
- Streaming:
  - Redis stream TTL and max-length prevent unbounded growth.
  - Blocking reads with timeouts balance responsiveness and resource usage.
- Observability:
  - Phoenix tracing with sanitization and batch processors reduces overhead and handles network issues gracefully.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Redis connectivity:
  - Celery app logs ping attempts and sanitized Redis URLs; verify credentials and network accessibility.
- Phoenix tracing:
  - Health checks detect unreachable endpoints; ensure Phoenix is running and reachable.
- Celery worker stability:
  - Async handler cleanup and shutdown hooks address “Task was destroyed” warnings.
- Authentication:
  - API key validation raises explicit HTTP exceptions; confirm API key presence and validity.
- Database:
  - Startup routine initializes tables; verify environment variables and permissions.

**Section sources**
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L67-L78)
- [app/modules/intelligence/tracing/phoenix_tracer.py](file://app/modules/intelligence/tracing/phoenix_tracer.py#L46-L69)
- [app/modules/auth/unified_auth_service.py](file://app/modules/auth/unified_auth_service.py#L1-L800)
- [app/main.py](file://app/main.py#L185-L207)

## Conclusion
Potpie’s architecture combines a modular FastAPI application, robust background processing via Celery, and a layered persistence model with PostgreSQL, Neo4j, and Redis. Cross-cutting concerns like authentication, monitoring, and error handling are integrated early in the lifecycle. The deployment topology separates API and worker services, enabling scalability and operational simplicity.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Deployment Topology
- API service: Runs the FastAPI application behind Supervisor and exposes ports for the app and monitoring.
- Celery service: Runs Celery workers and Flower for task monitoring.
- Infrastructure: PostgreSQL, Neo4j, and Redis managed via Docker Compose.

```mermaid
graph TB
subgraph "Host"
API_SRV["API Container<br/>api.Dockerfile"]
CELERY_SRV["Celery Container<br/>celery.Dockerfile"]
INFRA["Infrastructure Containers<br/>docker-compose.yaml"]
end
API_SRV --> INFRA
CELERY_SRV --> INFRA
```

**Diagram sources**
- [deployment/prod/mom-api/api.Dockerfile](file://deployment/prod/mom-api/api.Dockerfile#L1-L46)
- [deployment/prod/celery/celery.Dockerfile](file://deployment/prod/celery/celery.Dockerfile#L1-L46)
- [docker-compose.yaml](file://docker-compose.yaml#L1-L57)