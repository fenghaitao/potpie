# Data Flow Architecture

<cite>
**Referenced Files in This Document**
- [app/main.py](file://app/main.py)
- [app/api/router.py](file://app/api/router.py)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py)
- [app/celery/celery_app.py](file://app/celery/celery_app.py)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py)
- [app/celery/tasks/parsing_tasks.py](file://app/celery/tasks/parsing_tasks.py)
- [app/core/database.py](file://app/core/database.py)
- [app/core/config_provider.py](file://app/core/config_provider.py)
- [app/modules/parsing/graph_construction/parsing_controller.py](file://app/modules/parsing/graph_construction/parsing_controller.py)
- [app/modules/search/search_service.py](file://app/modules/search/search_service.py)
- [app/modules/media/media_service.py](file://app/modules/media/media_service.py)
- [app/modules/conversations/conversation/conversation_model.py](file://app/modules/conversations/conversation/conversation_model.py)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py)
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
This document explains Potpie’s data flow architecture from API requests to database persistence, real-time streaming, background processing, and caching. It covers:
- Request lifecycle from FastAPI route handlers through authentication and validation to service-layer operations and database transactions
- Real-time conversation streaming via Redis and Celery workers
- Asynchronous processing pipeline for agent interactions and parsing tasks
- Data transformation patterns across layers
- Transaction management for database operations
- Event-driven architecture for background tasks
- Knowledge graph data flow from parsing services to Neo4j
- Media file handling pipeline and integration flows for external services

## Project Structure
Potpie follows a modular FastAPI application with dedicated modules for authentication, conversations, parsing, search, media, integrations, and intelligence. Celery workers handle background tasks, while Redis streams provide real-time updates. PostgreSQL persists structured data, and Neo4j stores knowledge graph data.

```mermaid
graph TB
subgraph "API Layer"
FastAPI["FastAPI App<br/>app/main.py"]
Routers["Routers<br/>app/api/router.py<br/>conversations_router.py"]
end
subgraph "Service Layer"
Controllers["Controllers<br/>parsing_controller.py"]
Services["Services<br/>SearchService<br/>MediaService"]
Agents["Agent Tasks<br/>agent_tasks.py"]
end
subgraph "Background Processing"
Celery["Celery App<br/>celery_app.py"]
Workers["Workers<br/>agent_tasks.py<br/>parsing_tasks.py"]
Redis["Redis Streams<br/>redis_streaming.py"]
end
subgraph "Persistence"
DB["PostgreSQL<br/>database.py"]
PGModels["ORM Models<br/>conversation_model.py"]
Cache["Inference Cache<br/>inference_cache_model.py"]
Neo4j["Neo4j (knowledge graph)"]
end
FastAPI --> Routers
Routers --> Controllers
Controllers --> Services
Services --> DB
DB --> PGModels
Controllers --> Celery
Celery --> Workers
Workers --> Redis
Redis --> Routers
Services --> Cache
Controllers --> Neo4j
```

**Diagram sources**
- [app/main.py](file://app/main.py#L1-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L1-L622)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L1-L460)
- [app/celery/tasks/parsing_tasks.py](file://app/celery/tasks/parsing_tasks.py#L1-L58)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/conversations/conversation/conversation_model.py](file://app/modules/conversations/conversation/conversation_model.py#L1-L60)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)

**Section sources**
- [app/main.py](file://app/main.py#L1-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L1-L622)
- [app/core/database.py](file://app/core/database.py#L1-L117)

## Core Components
- FastAPI Application: Initializes CORS, logging, routers, and database on startup.
- Routers: Expose endpoints for conversations, parsing, search, media, integrations, and agents.
- Controllers: Coordinate business logic and orchestrate service operations.
- Services: Implement domain-specific operations (search, media, parsing).
- Celery App and Tasks: Execute long-running work asynchronously and publish streaming updates.
- Redis Stream Manager: Publishes and consumes streaming events for real-time UI updates.
- Database: SQLAlchemy engine/session factories and async session helpers for transactional operations.
- Models: ORM models for conversations, projects, and inference cache.
- Config Provider: Centralized configuration for Redis, Neo4j, storage providers, and streaming parameters.

**Section sources**
- [app/main.py](file://app/main.py#L46-L217)
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L1-L622)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L1-L473)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/conversations/conversation/conversation_model.py](file://app/modules/conversations/conversation/conversation_model.py#L1-L60)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

## Architecture Overview
The system uses an event-driven architecture:
- API requests enter via FastAPI routers and depend on database sessions.
- Authentication and validation middleware enforce access and usage limits.
- Controllers delegate to services for business logic.
- Long-running operations are offloaded to Celery workers.
- Redis streams deliver incremental updates to clients.
- PostgreSQL persists structured data; Neo4j stores knowledge graph artifacts.
- Caching strategies (inference cache) accelerate repeated computations.

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "FastAPI Router"
participant Controller as "Controller"
participant Service as "Service"
participant DB as "PostgreSQL"
participant Celery as "Celery App"
participant Worker as "Agent/Parsing Task"
participant Redis as "Redis Streams"
Client->>API : HTTP Request
API->>Controller : Route handler
Controller->>Service : Business operation
Service->>DB : Transactional reads/writes
DB-->>Service : Results
Service-->>Controller : Response
Controller-->>API : Response
API-->>Client : Response
Note over Controller,Celery : For long-running tasks
Controller->>Celery : Enqueue task
Celery->>Worker : Execute task
Worker->>Redis : Publish streaming events
Redis-->>Client : SSE updates
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L90-L218)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L160-L286)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L11-L25)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)
- [app/core/database.py](file://app/core/database.py#L100-L116)

## Detailed Component Analysis

### Request Lifecycle: Authentication, Validation, and Service Layer
- Authentication and usage checks occur at the router level for both API v1 and v2 endpoints.
- Controllers instantiate service objects and perform validations before delegating to background tasks or immediate processing.
- Database sessions are injected via dependency functions to ensure proper transaction boundaries.

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "API Router"
participant Auth as "Auth Middleware"
participant Controller as "ConversationController"
participant Service as "ConversationService"
participant DB as "PostgreSQL"
Client->>API : POST /api/v1/conversations/
API->>Auth : Validate API key and usage
Auth-->>API : User context
API->>Controller : create_conversation()
Controller->>Service : create_conversation()
Service->>DB : Insert conversation
DB-->>Service : Commit
Service-->>Controller : Conversation ID
Controller-->>API : Response
API-->>Client : Response
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L96-L121)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L82-L102)
- [app/core/database.py](file://app/core/database.py#L100-L116)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L56-L88)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L82-L102)
- [app/core/database.py](file://app/core/database.py#L100-L116)

### Real-Time Conversations: Streaming with Redis and Celery
- Clients send messages via conversation endpoints with optional streaming.
- The system generates a deterministic run_id and starts a background Celery task.
- The worker publishes incremental events to Redis streams; clients consume via Server-Sent Events.
- Redis TTL and max-length controls ensure efficient stream lifecycle management.

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "Conversation Router"
participant Celery as "Celery App"
participant Task as "execute_agent_background"
participant Redis as "Redis Stream Manager"
participant SSE as "StreamingResponse"
Client->>API : POST /conversations/{id}/message/?stream=true
API->>Celery : start_celery_task_and_stream(...)
Celery->>Task : delay(run_id, ...)
Task->>Redis : publish_event("start")
Task->>Redis : publish_event("chunk") x N
Task->>Redis : publish_event("end")
Redis-->>SSE : Stream events
SSE-->>Client : SSE chunks
```

**Diagram sources**
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L160-L286)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L11-L25)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)

**Section sources**
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L160-L286)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L1-L460)

### Asynchronous Processing Pipeline: Agent and Regeneration Tasks
- Agent tasks execute conversation logic, persist messages, and stream incremental results.
- Regeneration tasks reuse prior attachments and node contexts to regenerate responses.
- Both use BaseTask’s async session and publish standardized events to Redis.

```mermaid
flowchart TD
Start(["Task Received"]) --> Init["Initialize Stores and Services"]
Init --> StartEvent["Publish 'start' event"]
StartEvent --> Process["Process message or regenerate"]
Process --> Chunk{"More chunks?"}
Chunk --> |Yes| PublishChunk["Publish 'chunk' event"]
PublishChunk --> CheckCancel{"Cancelled?"}
CheckCancel --> |Yes| Flush["Flush partial buffer"]
Flush --> EndEvent["Publish 'end' with status 'cancelled'"]
CheckCancel --> |No| Chunk
Chunk --> |No| Complete["Publish 'end' with status 'completed'"]
Complete --> End(["Task Completed"])
EndEvent --> End
```

**Diagram sources**
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L36-L246)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)

**Section sources**
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L1-L460)

### Database Transactions and Sessions
- Synchronous and asynchronous session factories manage transaction boundaries.
- Celery tasks use a fresh async session to avoid cross-task Future binding issues.
- Startup initializes database tables and seeds system prompts.

```mermaid
classDiagram
class Database {
+engine
+async_engine
+get_db()
+get_async_db()
+create_celery_async_session()
}
class ConversationModel {
+id
+user_id
+project_ids
+agent_ids
+status
}
Database --> ConversationModel : "ORM mapping"
```

**Diagram sources**
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/conversations/conversation/conversation_model.py](file://app/modules/conversations/conversation/conversation_model.py#L1-L60)

**Section sources**
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/conversations/conversation/conversation_model.py](file://app/modules/conversations/conversation/conversation_model.py#L1-L60)

### Knowledge Graph Data Flow: Parsing to Neo4j
- ParsingController orchestrates repository parsing, project registration, and task submission.
- ParsingService performs graph construction; results are persisted and indexed.
- Neo4j is configured centrally via ConfigProvider; parsing tasks can integrate with Neo4j for graph updates.

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "Parsing Router"
participant Controller as "ParsingController"
participant Celery as "Celery App"
participant Task as "process_parsing"
participant Neo4j as "Neo4j"
Client->>API : POST /parse
API->>Controller : parse_directory()
Controller->>Celery : process_parsing.delay(...)
Celery->>Task : Execute parsing
Task->>Neo4j : Build/Update knowledge graph
Task-->>Controller : Status
Controller-->>API : Response
API-->>Client : Response
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L123-L147)
- [app/modules/parsing/graph_construction/parsing_controller.py](file://app/modules/parsing/graph_construction/parsing_controller.py#L42-L304)
- [app/celery/tasks/parsing_tasks.py](file://app/celery/tasks/parsing_tasks.py#L17-L54)
- [app/core/config_provider.py](file://app/core/config_provider.py#L69-L73)

**Section sources**
- [app/modules/parsing/graph_construction/parsing_controller.py](file://app/modules/parsing/graph_construction/parsing_controller.py#L1-L384)
- [app/celery/tasks/parsing_tasks.py](file://app/celery/tasks/parsing_tasks.py#L1-L58)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

### Media File Handling Pipeline
- MediaService validates, processes, and uploads images to configured object storage.
- Attachments are linked to messages; signed URLs enable controlled access.
- Multimodal support is toggled via configuration; validation ensures allowed types and sizes.

```mermaid
flowchart TD
Upload["Upload Image"] --> Validate["Validate MIME and size"]
Validate --> Process["Resize/convert if needed"]
Process --> Store["Upload to object storage"]
Store --> Record["Create attachment record"]
Record --> Link["Link to message"]
Link --> Done["Done"]
```

**Diagram sources**
- [app/modules/media/media_service.py](file://app/modules/media/media_service.py#L101-L185)

**Section sources**
- [app/modules/media/media_service.py](file://app/modules/media/media_service.py#L1-L686)

### Search and Caching Strategies
- SearchService queries a prebuilt codebase index and ranks results by relevance.
- InferenceCache model stores computed embeddings and metadata for reuse.
- ConfigProvider centralizes Redis and streaming parameters for consistent behavior.

```mermaid
classDiagram
class SearchService {
+search_codebase(project_id, query)
+bulk_create_search_indices(nodes)
+clone_search_indices(input_project_id, output_project_id)
}
class InferenceCache {
+content_hash
+project_id
+node_type
+content_length
+inference_data
+embedding_vector
+tags
+created_at
+last_accessed
+access_count
}
SearchService --> InferenceCache : "caches/references"
```

**Diagram sources**
- [app/modules/search/search_service.py](file://app/modules/search/search_service.py#L1-L147)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)

**Section sources**
- [app/modules/search/search_service.py](file://app/modules/search/search_service.py#L1-L147)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)
- [app/core/config_provider.py](file://app/core/config_provider.py#L208-L218)

## Dependency Analysis
The system exhibits clear separation of concerns:
- API routers depend on controllers and services
- Controllers depend on services and Celery for background tasks
- Celery tasks depend on Redis for streaming and database sessions for persistence
- Redis is used for eventing and session management
- Configuration provider centralizes environment-dependent settings

```mermaid
graph LR
API["API Router"] --> Controller["Controller"]
Controller --> Service["Service"]
Controller --> Celery["Celery App"]
Celery --> Task["Tasks"]
Task --> Redis["Redis Streams"]
Service --> DB["PostgreSQL"]
Controller --> DB
Service --> Cache["Inference Cache"]
Controller --> Neo4j["Neo4j"]
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L1-L622)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L1-L460)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

**Section sources**
- [app/api/router.py](file://app/api/router.py#L1-L318)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L1-L622)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L1-L460)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L1-L248)
- [app/core/database.py](file://app/core/database.py#L1-L117)
- [app/modules/parsing/models/inference_cache_model.py](file://app/modules/parsing/models/inference_cache_model.py#L1-L36)
- [app/core/config_provider.py](file://app/core/config_provider.py#L1-L246)

## Performance Considerations
- Asynchronous sessions: Use async session factories for non-blocking IO and avoid pooled connections in Celery workers to prevent Future binding issues.
- Redis streaming: Tune TTL and max-len to balance memory usage and replayability.
- Worker tuning: Prefetch multiplier, task acks late, and memory limits prevent resource exhaustion and improve reliability.
- Multimodal processing: Validate and resize images early to reduce downstream processing overhead.
- Search relevance: Weighting and similarity scoring should be benchmarked against corpus size and query patterns.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Redis connectivity: Celery app pings the Redis backend on startup; failures are logged with sanitized URLs.
- Worker shutdown: Celery cleans up pending async tasks and removes async handlers to avoid “Task was destroyed” warnings.
- Task cancellation: Redis cancellation keys allow clients to stop long-running generations; workers flush buffers before ending.
- Media upload errors: Rollback and cleanup ensure orphaned attachments are removed; signed URL generation falls back to direct endpoints.

**Section sources**
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L70-L78)
- [app/celery/celery_app.py](file://app/celery/celery_app.py#L405-L453)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L177-L234)
- [app/modules/media/media_service.py](file://app/modules/media/media_service.py#L179-L185)

## Conclusion
Potpie’s architecture cleanly separates concerns across API, service, background processing, and persistence layers. Real-time streaming leverages Redis and Celery for responsive user experiences, while PostgreSQL and Neo4j provide robust data and knowledge graph storage. Carefully tuned sessions, worker configurations, and caching strategies ensure scalability and reliability.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Data Flow Diagrams

#### Conversation Creation and Streaming
```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "API Router"
participant Controller as "ConversationController"
participant Celery as "Celery"
participant Worker as "Agent Task"
participant Redis as "Redis"
Client->>API : POST /api/v1/conversations/
API->>Controller : create_conversation()
Controller-->>API : Conversation ID
API-->>Client : Response
Client->>API : POST /api/v1/conversations/{id}/message/?stream=true
API->>Celery : start_celery_task_and_stream
Celery->>Worker : execute_agent_background
Worker->>Redis : publish "start"
Worker->>Redis : publish "chunk" x N
Worker->>Redis : publish "end"
Redis-->>Client : SSE stream
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L96-L121)
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L160-L286)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L11-L25)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)

#### Code Parsing Pipeline
```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "Parsing Router"
participant Controller as "ParsingController"
participant Celery as "Celery"
participant Task as "process_parsing"
participant DB as "PostgreSQL"
participant Neo4j as "Neo4j"
Client->>API : POST /api/v1/parse
API->>Controller : parse_directory()
Controller->>Celery : process_parsing.delay(...)
Celery->>Task : Execute
Task->>DB : Persist project/graph state
Task->>Neo4j : Update knowledge graph
Task-->>Controller : Status
Controller-->>API : Response
API-->>Client : Response
```

**Diagram sources**
- [app/api/router.py](file://app/api/router.py#L123-L147)
- [app/modules/parsing/graph_construction/parsing_controller.py](file://app/modules/parsing/graph_construction/parsing_controller.py#L42-L304)
- [app/celery/tasks/parsing_tasks.py](file://app/celery/tasks/parsing_tasks.py#L17-L54)

#### Agent Interaction and Regeneration
```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "Conversation Router"
participant Celery as "Celery"
participant AgentTask as "execute_agent_background"
participant RegenTask as "execute_regenerate_background"
participant Redis as "Redis"
Client->>API : POST /conversations/{id}/message/?stream=true
API->>Celery : start_celery_task_and_stream
Celery->>AgentTask : Execute
AgentTask->>Redis : publish "chunk" x N
AgentTask->>Redis : publish "end"
Client->>API : POST /conversations/{id}/regenerate/?stream=true
API->>Celery : execute_regenerate_background
Celery->>RegenTask : Execute
RegenTask->>Redis : publish "chunk" x N
RegenTask->>Redis : publish "end"
```

**Diagram sources**
- [app/modules/conversations/conversations_router.py](file://app/modules/conversations/conversations_router.py#L288-L417)
- [app/celery/tasks/agent_tasks.py](file://app/celery/tasks/agent_tasks.py#L249-L460)
- [app/modules/conversations/utils/redis_streaming.py](file://app/modules/conversations/utils/redis_streaming.py#L21-L63)