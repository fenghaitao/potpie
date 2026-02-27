11-Development and Deployment

# Page: Development and Deployment

# Development and Deployment

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [LICENSE](LICENSE)
- [contributing.md](contributing.md)

</details>



This document provides operational guidance for running and maintaining Potpie across development and production environments. It covers service orchestration, prerequisites, configuration management, and the lifecycle of core processes.

For detailed information about specific deployment modes, see:
- Development mode setup and local model usage: [Development Mode](#11.1)
- Production configuration with Firebase, GitHub App, and cloud services: [Production Deployment](#11.2)
- Observability tools including Phoenix tracing and Sentry: [Monitoring and Observability](#11.3)

For comprehensive environment variable documentation, see [Environment Configuration](#8.3). For configuration management internals, see [Configuration Provider](#8.1).

---

## Service Orchestration Architecture

Potpie uses shell scripts to orchestrate multiple services that must start in a specific sequence to ensure proper initialization.

### Service Dependency Chain

```mermaid
graph TB
    Start["./start.sh"]
    Docker["docker compose up -d<br/>PostgreSQL, Neo4j, Redis"]
    WaitPG["Wait for PostgreSQL<br/>Health Check Loop"]
    Migrate["alembic upgrade head<br/>Database Migrations"]
    FastAPI["gunicorn -w 2<br/>app.main:app<br/>Port 8001"]
    Celery["celery -A app.core.celery_app worker<br/>-Q dev"]
    Phoenix["phoenix serve<br/>(Optional)<br/>Port 6006"]
    
    Start --> Docker
    Docker --> WaitPG
    WaitPG --> Migrate
    Migrate --> FastAPI
    Migrate --> Celery
    Start -.optional.-> Phoenix
    
    Stop["./stop.sh"]
    KillProc["pkill gunicorn<br/>pkill celery"]
    DockerDown["docker compose down"]
    
    Stop --> KillProc
    KillProc --> DockerDown
```

**Service Startup Diagram**: Shows the orchestrated startup sequence managed by [start.sh:1-70]()

The startup sequence ensures:
1. **Docker services initialize first**: PostgreSQL must be ready before migrations
2. **Database migrations complete**: Alembic applies schema changes
3. **Application services start in parallel**: FastAPI and Celery can start simultaneously after migrations
4. **Optional tracing**: Phoenix can run independently for local development

**Sources**: [start.sh:1-70](), [stop.sh:1-16](), [README.md:256-304]()

---

## Prerequisites and Dependencies

### Required Software

| Component | Version | Installation | Purpose |
|-----------|---------|--------------|---------|
| **Python** | 3.11+ | System package manager | Application runtime |
| **uv** | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Fast Python package installer |
| **Docker** | Latest | [docker.com](https://docker.com) | Container orchestration for PostgreSQL, Neo4j, Redis |
| **Git** | Latest | System package manager | Repository access |

**Sources**: [README.md:121-126](), [GETTING_STARTED.md:5-11]()

### Dependency Installation

```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ensure ~/.local/bin is in PATH
export PATH="$HOME/.local/bin:$PATH"

# Install Python dependencies
uv sync
```

The `uv sync` command reads [pyproject.toml]() and creates a `.venv` directory with all dependencies installed. This includes:
- FastAPI and uvicorn for web server
- Celery for background tasks
- psycopg2 for PostgreSQL
- neo4j driver for graph database
- redis for caching and streaming
- All AI/ML libraries (litellm, sentence-transformers, etc.)

**Sources**: [README.md:174-214](), [GETTING_STARTED.md:23-29]()

---

## Service Lifecycle Management

### Start Script Implementation

```mermaid
flowchart TB
    subgraph "start.sh Execution Flow"
        CheckDocker["Check Docker Running"]
        StartCompose["docker compose up -d<br/>neo4j, postgres, redis"]
        WaitLoop["while ! docker exec postgres<br/>pg_isready -U postgres"]
        Sleep["sleep 1"]
        AlembicMigrate["source .venv/bin/activate<br/>alembic upgrade head"]
        StartGunicorn["gunicorn -w 2<br/>--bind 0.0.0.0:8001<br/>--log-level info<br/>app.main:app"]
        StartCelery["celery -A app.core.celery_app<br/>worker --loglevel=info<br/>-Q CELERY_QUEUE_NAME"]
        
        CheckDocker -->|Failed| Error["Exit 1:<br/>Docker not running"]
        CheckDocker -->|Success| StartCompose
        StartCompose --> WaitLoop
        WaitLoop -->|Not Ready| Sleep
        Sleep --> WaitLoop
        WaitLoop -->|Ready| AlembicMigrate
        AlembicMigrate --> StartGunicorn
        AlembicMigrate --> StartCelery
    end
    
    subgraph "stop.sh Execution Flow"
        KillGunicorn["pkill -f gunicorn"]
        KillCelery["pkill -f celery"]
        ComposeDown["docker compose down"]
        
        KillGunicorn --> KillCelery
        KillCelery --> ComposeDown
    end
```

**Service Lifecycle Flow**: Maps shell script logic to process management

**Sources**: [start.sh:1-70](), [stop.sh:1-16]()

### Process Management Details

#### FastAPI (Gunicorn)
- **Workers**: 2 processes (configurable)
- **Port**: 8001 (exposed via `docker-compose.yml`)
- **Binding**: `0.0.0.0` for Docker networking
- **Log Level**: `info` for production visibility
- **Entry Point**: `app.main:app` refers to the FastAPI application instance

#### Celery Worker
- **Broker**: Redis at `BROKER_URL` (from `.env`)
- **Queue**: Uses `CELERY_QUEUE_NAME` environment variable (e.g., "dev", "prod")
- **Task Module**: `app.core.celery_app` contains task definitions
- **Concurrency**: Default (number of CPUs)
- **Key Tasks**: `process_parsing`, `execute_message_background`, `execute_regenerate_background`

**Sources**: [start.sh:45-60](), [README.md:271-277]()

---

## Configuration Hierarchy

### Environment Variable Loading

```mermaid
graph LR
    subgraph "Configuration Sources"
        Template[".env.template<br/>Default Values"]
        EnvFile[".env<br/>User Overrides"]
        SystemEnv["System Environment<br/>Variables"]
    end
    
    subgraph "Runtime Access"
        ConfigProvider["ConfigProvider<br/>Singleton"]
        OSEnviron["os.environ"]
    end
    
    Template -.documents.-> EnvFile
    EnvFile --> OSEnviron
    SystemEnv --> OSEnviron
    OSEnviron --> ConfigProvider
    
    subgraph "Services"
        AuthService["AuthService"]
        ParsingService["ParsingService"]
        ProviderService["ProviderService"]
    end
    
    ConfigProvider --> AuthService
    ConfigProvider --> ParsingService
    ConfigProvider --> ProviderService
```

**Configuration Flow**: Environment variables flow from `.env` through `ConfigProvider` to services

### Critical Configuration Variables

| Variable | Required | Purpose | Default |
|----------|----------|---------|---------|
| `isDevelopmentMode` | No | Enable auth bypass and local models | `disabled` |
| `ENV` | Yes | Environment context (development/stage/production) | - |
| `POSTGRES_SERVER` | Yes | PostgreSQL connection string | - |
| `NEO4J_URI` | Yes | Neo4j bolt connection | `bolt://127.0.0.1:7687` |
| `NEO4J_USERNAME` | Yes | Neo4j authentication | `neo4j` |
| `NEO4J_PASSWORD` | Yes | Neo4j authentication | - |
| `REDISHOST` | Yes | Redis host for caching/streams | `127.0.0.1` |
| `REDISPORT` | Yes | Redis port | `6379` |
| `BROKER_URL` | Yes | Celery broker (Redis) | - |
| `CELERY_QUEUE_NAME` | Yes | Celery queue identifier | `dev` |
| `defaultUsername` | No | Development mode user | - |
| `PROJECT_PATH` | Yes | Repository clone directory | `projects` |
| `CHAT_MODEL` | Yes | Agent reasoning model | - |
| `INFERENCE_MODEL` | Yes | Knowledge graph generation model | - |

**Sources**: [README.md:186-204](), [GETTING_STARTED.md:15-47](), [contributing.md:117-125]()

### Development vs Production Configuration

The distinction between `ENV` and `isDevelopmentMode` is important:

- **`ENV=development`**: Runs Potpie locally but requires all production dependencies (Firebase, GitHub App, GCP Secret Manager)
- **`isDevelopmentMode=enabled`**: Disables authentication, GitHub App requirements, and cloud dependencies; enables local repository parsing

Example development configuration:
```bash
isDevelopmentMode=enabled
ENV=development
POSTGRES_SERVER=postgresql://postgres:mysecretpassword@localhost:5432/momentum
defaultUsername=defaultuser
INFERENCE_MODEL=ollama_chat/qwen2.5-coder:7b
CHAT_MODEL=ollama_chat/qwen2.5-coder:7b
```

Example production configuration:
```bash
isDevelopmentMode=disabled
ENV=production
POSTGRES_SERVER=postgresql://user:pass@prod-host:5432/potpie
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----...
```

**Sources**: [contributing.md:117-125](), [README.md:189-190](), [GETTING_STARTED.md:17-21]()

---

## Database and Migration Management

### Migration Execution

The [start.sh:40-42]() script activates the virtual environment and runs Alembic migrations:

```bash
source .venv/bin/activate
alembic upgrade head
```

This applies all pending migrations from the `alembic/versions/` directory to the PostgreSQL database specified in `POSTGRES_SERVER`.

### Schema Management

| Table | Purpose | Migration Responsibility |
|-------|---------|-------------------------|
| `users` | User accounts and authentication state | Core schema migrations |
| `user_auth_providers` | OAuth tokens and provider linking | Auth system migrations |
| `projects` | Repository metadata and parsing status | Parsing system migrations |
| `conversations` | Chat session metadata | Conversation system migrations |
| `messages` | Conversation history | Conversation system migrations |
| `message_attachments` | Multimodal content references | Media system migrations |
| `custom_agents` | User-defined agent configurations | Agent system migrations |
| `prompts` | System and custom prompts | Prompt system migrations |
| `agent_prompt_mappings` | Agent-prompt associations | Agent system migrations |
| `pending_provider_links` | Account consolidation flow | Auth system migrations |

**Sources**: [start.sh:40-42](), [README.md:274]()

### Health Check Loop

```python
# Pseudo-code representation of start.sh:25-38
while True:
    result = subprocess.run(
        ["docker", "exec", "postgres", "pg_isready", "-U", "postgres"],
        capture_output=True
    )
    if result.returncode == 0:
        break
    time.sleep(1)
    print("Waiting for PostgreSQL...")
```

This ensures migrations don't run against an unready database, preventing connection errors during startup.

**Sources**: [start.sh:25-38]()

---

## Process Management

### Gunicorn Configuration

```mermaid
graph TB
    subgraph "Gunicorn Master Process"
        Master["gunicorn master<br/>PID management"]
    end
    
    subgraph "Worker Processes"
        Worker1["Worker 1<br/>app.main:app<br/>FastAPI instance"]
        Worker2["Worker 2<br/>app.main:app<br/>FastAPI instance"]
    end
    
    subgraph "FastAPI Application"
        Routers["API Routers<br/>auth, parse, conversations<br/>agents, media"]
        Middleware["Middleware<br/>CORS, Auth"]
    end
    
    Master --> Worker1
    Master --> Worker2
    Worker1 --> Routers
    Worker2 --> Routers
    Routers --> Middleware
    
    HTTP["HTTP Requests<br/>Port 8001"] --> Master
```

**Gunicorn Architecture**: Master process spawns 2 worker processes, each running a FastAPI application instance

The `-w 2` flag creates 2 worker processes, allowing concurrent request handling. Each worker has its own Python interpreter and imports the application independently.

**Sources**: [start.sh:45-50]()

### Celery Worker Architecture

```mermaid
graph TB
    subgraph "Celery Worker Process"
        Worker["celery worker<br/>-A app.core.celery_app"]
        TaskQueue["Redis Queue<br/>CELERY_QUEUE_NAME"]
    end
    
    subgraph "Task Execution"
        ProcessParsing["process_parsing<br/>Repository ingestion"]
        ExecuteMessage["execute_message_background<br/>Long-running conversations"]
        ExecuteRegen["execute_regenerate_background<br/>Message regeneration"]
    end
    
    subgraph "Task Dispatchers"
        ParseController["ParsingController<br/>.delay()"]
        ConvRouter["ConversationRouter<br/>.apply_async()"]
    end
    
    ParseController -.dispatch.-> TaskQueue
    ConvRouter -.dispatch.-> TaskQueue
    TaskQueue --> Worker
    Worker --> ProcessParsing
    Worker --> ExecuteMessage
    Worker --> ExecuteRegen
```

**Celery Task Flow**: Controllers dispatch tasks to Redis queue, Celery worker consumes and executes them

**Sources**: [start.sh:52-60](), [README.md:271-277]()

### Process Termination

The [stop.sh:1-16]() script gracefully terminates services:

1. **Kill FastAPI**: `pkill -f "gunicorn"` sends SIGTERM to all gunicorn processes
2. **Kill Celery**: `pkill -f "celery"` terminates Celery worker
3. **Stop Docker**: `docker compose down` stops PostgreSQL, Neo4j, Redis containers

The `|| true` suffix prevents script failure if processes aren't running, enabling idempotent shutdown.

**Sources**: [stop.sh:1-16]()

---

## Docker Infrastructure

### Service Composition

The `docker-compose.yml` defines three core services:

| Service | Image | Exposed Port | Volume Mounts | Purpose |
|---------|-------|--------------|---------------|---------|
| **postgres** | `postgres:15` | 5432 | `postgres_data:/var/lib/postgresql/data` | Relational data storage |
| **neo4j** | `neo4j:5.x` | 7474 (HTTP), 7687 (Bolt) | `neo4j_data:/data` | Knowledge graph storage |
| **redis** | `redis:7` | 6379 | `redis_data:/data` | Caching, streaming, task queue |

### Network Configuration

All services run on the default Docker Compose network, enabling inter-container communication via service names:
- FastAPI connects to `postgres` at `POSTGRES_SERVER=postgresql://postgres:password@postgres:5432/momentum`
- Neo4j accessible via `NEO4J_URI=bolt://neo4j:7687` (internal) or `bolt://127.0.0.1:7687` (host)
- Redis accessible via `REDISHOST=redis` (internal) or `REDISHOST=127.0.0.1` (host)

For local development, ports are mapped to localhost, allowing external tools to connect (e.g., Neo4j Browser at `http://localhost:7474`).

**Sources**: [start.sh:15-22](), [README.md:191-196]()

### Volume Persistence

Named volumes ensure data persists across container restarts:
- **postgres_data**: Stores user accounts, projects, conversations, messages
- **neo4j_data**: Stores code graph nodes and relationships
- **redis_data**: Stores cached data and stream backups

Running `docker compose down` stops containers but preserves volumes. To reset all data, use `docker compose down -v`.

**Sources**: [start.sh:15-22]()

---

## Development vs Production Modes

### Development Mode Characteristics

When `isDevelopmentMode=enabled`:

1. **Authentication Bypass**: [app/modules/auth/auth_service.py]() returns a mock user based on `defaultUsername`
   ```python
   # From auth_service_test.py:231-246
   if os.getenv("isDevelopmentMode") == "enabled":
       return {
           "user_id": os.getenv("defaultUsername", "dev_user"),
           "email": "defaultuser@potpie.ai"
       }
   ```

2. **Local Repository Parsing**: [app/modules/parsing/parsing_service.py]() accepts `repo_path` parameter for local directories

3. **Minimal Dependencies**: No Firebase, GitHub App, or GCP Secret Manager required

4. **Local Model Usage**: Can use Ollama models like `ollama_chat/qwen2.5-coder:7b` without API keys

**Sources**: [app/modules/auth/tests/auth_service_test.py:231-246](), [README.md:189-190](), [GETTING_STARTED.md:1-61](), [contributing.md:117-125]()

### Production Mode Requirements

When `isDevelopmentMode=disabled` (production):

| Requirement | Configuration | Purpose |
|-------------|---------------|---------|
| **Firebase Authentication** | `firebase_service_account.json` in root | User identity and token verification |
| **GitHub App** | `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY` | Repository access with proper permissions |
| **GitHub PAT Pool** | `GH_TOKEN_LIST` (comma-separated) | Fallback auth and rate limit distribution |
| **PostHog Analytics** | `POSTHOG_API_KEY`, `POSTHOG_HOST` | User behavior tracking |
| **GCP Secret Manager** | Application Default Credentials | Secure API key storage |
| **Object Storage** | S3/GCS/Azure credentials | Image storage for multimodal features |

**Sources**: [GETTING_STARTED.md:63-172](), [README.md:217-254]()

### Mode Detection in Code

```mermaid
graph LR
    Request["HTTP Request"]
    AuthMiddleware["auth_service.check_auth()"]
    DevCheck{"isDevelopmentMode<br/>== 'enabled'?"}
    MockUser["Return Mock User<br/>{user_id: defaultUsername}"]
    FirebaseVerify["firebase_admin.auth<br/>.verify_id_token()"]
    Success["Authenticated Request"]
    
    Request --> AuthMiddleware
    AuthMiddleware --> DevCheck
    DevCheck -->|Yes| MockUser
    DevCheck -->|No| FirebaseVerify
    MockUser --> Success
    FirebaseVerify --> Success
```

**Authentication Mode Selection**: Development mode bypasses Firebase token verification

**Sources**: [app/modules/auth/tests/auth_service_test.py:230-246]()

---

## Platform-Specific Scripts

### Windows Support

Potpie provides PowerShell equivalents for Windows:

- **start.ps1**: Uses `Start-Process` instead of `&` for backgrounding
- **stop.ps1**: Uses `Get-Process | Where-Object { $_.CommandLine -match 'uvicorn' }` instead of `pkill`

Key differences:
- Windows uses `uvicorn` directly instead of `gunicorn` (WSGI server not supported on Windows)
- Process termination uses PowerShell cmdlets instead of Unix signals

**Sources**: [README.md:265-270](), [stop.ps1:1-15]()

### Cross-Platform Compatibility

The core application is platform-agnostic, but startup scripts differ:

| Feature | Linux/macOS | Windows |
|---------|-------------|---------|
| Shell | bash | PowerShell |
| Process backgrounding | `&` | `Start-Process` |
| Process killing | `pkill -f` | `Get-Process \| Stop-Process` |
| Virtual environment activation | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| WSGI server | gunicorn | uvicorn (ASGI only) |

**Sources**: [start.sh:1-70](), [stop.sh:1-16](), [stop.ps1:1-15]()

---

## Optional Services

### Phoenix Tracing (Development Only)

Phoenix provides LLM observability for local development:

```bash
# Start Phoenix server in separate terminal
phoenix serve
```

- **Default Port**: 6006
- **UI Access**: `http://localhost:6006`
- **Auto-initialization**: `app.main` initializes Phoenix tracer on startup
- **Traces**: Captures LLM calls from ProviderService, agent execution flows, tool usage
- **Production**: Phoenix is NOT used in production; use Sentry for error tracking

**Sources**: [README.md:278-284]()

### UI Submodule

The `potpie-ui` repository is included as a Git submodule:

```bash
# Initialize submodule
git submodule update --init

# Navigate to UI directory
cd potpie-ui

# Checkout main branch
git checkout main
git pull origin main

# Build and start
pnpm build
pnpm start
```

The UI is a separate Next.js application that communicates with the FastAPI backend via HTTP requests to port 8001.

**Sources**: [README.md:132-170]()

---

## Common Deployment Patterns

### Development Workflow

```bash
# 1. Initial setup
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/potpie-ai/potpie.git
cd potpie
cp .env.template .env
# Edit .env: set isDevelopmentMode=enabled, configure models

# 2. Install dependencies
uv sync

# 3. Start services
./start.sh

# 4. (Optional) Start Phoenix tracing
phoenix serve

# 5. Use API
curl -X POST 'http://localhost:8001/api/v1/parse' \
  -H 'Content-Type: application/json' \
  -d '{"repo_path": "/path/to/local/repo", "branch_name": "main"}'

# 6. Stop services
./stop.sh
```

**Sources**: [README.md:174-304](), [GETTING_STARTED.md:1-61]()

### Production Workflow

```bash
# 1. Initial setup
# Complete Firebase, GitHub App, GCP setup first (see GETTING_STARTED.md)

# 2. Configure environment
cp .env.template .env
# Edit .env: set isDevelopmentMode=disabled, add all production credentials

# 3. Authenticate with GCP
gcloud init
gcloud auth application-default login

# 4. Install dependencies
uv sync

# 5. Start services
./start.sh

# 6. Monitor logs
tail -f logs/gunicorn.log
tail -f logs/celery.log
```

**Sources**: [GETTING_STARTED.md:63-172]()

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Docker not running" error | Docker daemon not started | Start Docker Desktop or `systemctl start docker` |
| Migration failures | PostgreSQL not ready | Wait for health check; verify `POSTGRES_SERVER` connection string |
| Import errors | Dependencies not installed | Run `uv sync` to install packages |
| Port 8001 already in use | Previous FastAPI instance running | Run `./stop.sh` or `pkill -f gunicorn` |
| Celery tasks not executing | Wrong queue name | Verify `CELERY_QUEUE_NAME` matches between `.env` and worker |
| Firebase auth errors in dev | `isDevelopmentMode` not set | Set `isDevelopmentMode=enabled` in `.env` |

### Log Locations

- **FastAPI**: stdout (captured by terminal or systemd)
- **Celery**: stdout (captured by terminal or systemd)
- **Docker services**: `docker compose logs postgres/neo4j/redis`
- **Phoenix**: `http://localhost:6006` (development only)

**Sources**: [start.sh:1-70](), [stop.sh:1-16](), [README.md:278-284]()