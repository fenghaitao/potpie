11.2-Production Deployment

# Page: Production Deployment

# Production Deployment

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [LICENSE](LICENSE)
- [contributing.md](contributing.md)

</details>



This document describes the configuration and deployment process for running Potpie in a production environment with full external service integrations. Production deployment requires configuring multiple external services including Firebase authentication, GitHub integration, Google Cloud Platform, database infrastructure, and observability tools.

For local development without external dependencies, see [Development Mode](#11.1). For monitoring and observability setup, see [Monitoring and Observability](#11.3).

## Production vs Development Mode

Potpie supports two distinct operational modes controlled by environment variables:

| Environment Variable | Purpose | Production Value | Development Value |
|---------------------|---------|------------------|-------------------|
| `ENV` | Deployment environment identifier | `production` or `staging` | `development` |
| `isDevelopmentMode` | Toggles dependency requirements | `disabled` or unset | `enabled` |

**Key Distinction**: `ENV=development` still requires Firebase, GCS, GitHub configuration, and other external services—it indicates the backend is running locally but with full production dependencies. `isDevelopmentMode=enabled` disables authentication, uses mock services, and supports local-only parsing without external service requirements.

In production, both variables should be configured for full service integration:
```bash
ENV=production
isDevelopmentMode=disabled
```

**Sources**: [contributing.md:117-125]()

## Production Architecture Overview

```mermaid
graph TB
    subgraph "External Authentication Services"
        FIREBASE["Firebase<br/>Authentication & Firestore"]
        GITHUB_APP["GitHub App<br/>OAuth & Repository Access"]
        GOOGLE_CLOUD["Google Cloud Platform<br/>Secret Manager & ADC"]
    end
    
    subgraph "Database Infrastructure"
        POSTGRES["PostgreSQL<br/>Relational Data Store"]
        NEO4J["Neo4j<br/>Code Knowledge Graph"]
        REDIS["Redis<br/>Cache & Message Broker"]
    end
    
    subgraph "Storage Services"
        STORAGE["Object Storage<br/>GCS/S3/Azure Blob"]
    end
    
    subgraph "Observability Services"
        POSTHOG["PostHog<br/>Product Analytics"]
        SENTRY["Sentry<br/>Error Tracking"]
        PHOENIX["Phoenix<br/>Distributed Tracing"]
    end
    
    subgraph "LLM Providers"
        OPENAI["OpenAI"]
        ANTHROPIC["Anthropic"]
        OTHER_LLM["Other LiteLLM Providers"]
    end
    
    subgraph "Potpie Application"
        FASTAPI["FastAPI Application<br/>app/main.py"]
        CELERY_WORKER["Celery Workers<br/>Background Processing"]
    end
    
    FASTAPI --> FIREBASE
    FASTAPI --> GITHUB_APP
    FASTAPI --> GOOGLE_CLOUD
    FASTAPI --> POSTGRES
    FASTAPI --> NEO4J
    FASTAPI --> REDIS
    FASTAPI --> STORAGE
    FASTAPI --> POSTHOG
    FASTAPI --> SENTRY
    FASTAPI --> PHOENIX
    FASTAPI --> OPENAI
    FASTAPI --> ANTHROPIC
    FASTAPI --> OTHER_LLM
    
    CELERY_WORKER --> REDIS
    CELERY_WORKER --> POSTGRES
    CELERY_WORKER --> NEO4J
    CELERY_WORKER --> GITHUB_APP
    CELERY_WORKER --> GOOGLE_CLOUD
    CELERY_WORKER --> STORAGE
```

**Production Deployment Dependencies**: Unlike development mode which can run with minimal dependencies, production requires all external services to be properly configured and accessible.

**Sources**: [GETTING_STARTED.md:63-172]()

## External Service Requirements

### Firebase Setup

Firebase provides authentication services and Firestore database for onboarding data.

**Setup Steps**:

1. **Create Firebase Project**: Navigate to [Firebase Console](https://console.firebase.google.com/) and create a new project.

2. **Generate Service Account Key**:
   - Navigate to Project Overview Gear ⚙ → Service Accounts tab
   - Generate new private key in Firebase Admin SDK section
   - Rename downloaded key to `firebase_service_account.json`
   - Place file in repository root directory

3. **Create Firebase App**:
   - Open Project Overview Gear ⚙
   - Create Firebase app
   - Copy configuration keys for hosting, storage, and services
   - Add keys to `.env` file

4. **Enable GitHub Authentication**:
   - Navigate to Authentication section
   - Enable GitHub sign-in provider
   - Create GitHub OAuth app and obtain client secret and client ID
   - Add credentials to Firebase
   - Copy callback URL from Firebase and add to GitHub app configuration

**Required Environment Variables**:
```bash
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CLIENT_EMAIL=your-client-email
FIREBASE_PRIVATE_KEY=your-private-key
FIREBASE_API_KEY=your-api-key
FIREBASE_AUTH_DOMAIN=your-auth-domain
FIREBASE_STORAGE_BUCKET=your-storage-bucket
```

**Sources**: [GETTING_STARTED.md:67-81](), [GETTING_STARTED.md:123-129]()

### GitHub App Configuration

GitHub App provides repository access and authentication integration.

**Permission Requirements**:

| Permission Category | Resource | Access Level |
|-------------------|----------|--------------|
| Repository Permissions | Contents | Read Only |
| Repository Permissions | Metadata | Read Only |
| Repository Permissions | Pull Requests | Read and Write |
| Repository Permissions | Secrets | Read Only |
| Repository Permissions | Webhook | Read Only |
| Organization Permissions | Members | Read Only |
| Account Permissions | Email Address | Read Only |

**Setup Steps**:

1. **Create GitHub App**: Visit [GitHub App Creation](https://github.com/settings/apps/new)

2. **Configure App Settings**:
   - Name: Choose relevant name (e.g., `potpie-auth`)
   - Homepage URL: `https://potpie.ai`
   - Webhook: Inactive
   - Set permissions as listed above

3. **Generate Private Key**:
   - Download private key from app settings
   - Place in project root directory
   - Format key using `format_pem.sh`:
   ```bash
   chmod +x format_pem.sh
   ./format_pem.sh your-key.pem
   ```
   - Copy formatted key output

4. **Install App**: Install the app to your organization/user account from the left sidebar

5. **Create Personal Access Token**: Generate classic token in GitHub Settings → Developer Settings → Personal Access Tokens

**Required Environment Variables**:
```bash
GITHUB_APP_ID=your-app-id
GITHUB_PRIVATE_KEY=formatted-private-key
GH_TOKEN_LIST=comma-separated-tokens
```

**Sources**: [GETTING_STARTED.md:92-120]()

### Google Cloud Platform Setup

Google Cloud Platform provides Secret Manager for secure API key storage and Application Default Credentials for service authentication.

```mermaid
graph LR
    subgraph "Google Cloud Services"
        SECRET_MGR["Secret Manager API<br/>Encrypted Storage"]
        ADC["Application Default Credentials<br/>Authentication"]
    end
    
    subgraph "Potpie Application"
        CONFIG["ConfigurationProvider<br/>app/modules/intelligence/provider/config_provider.py"]
        AUTH["Service Account<br/>service-account.json"]
    end
    
    CONFIG -->|"fetch secrets"| SECRET_MGR
    CONFIG -->|"authenticate via"| ADC
    AUTH -->|"alternative to"| ADC
    
    SECRET_MGR -->|"stores"| API_KEYS["API Keys:<br/>OPENAI_API_KEY<br/>ANTHROPIC_API_KEY<br/>etc."]
```

**Setup Steps**:

1. **Install gcloud CLI**:
   ```bash
   # Follow official installation guide
   gcloud init
   ```
   - Configure default compute region when prompted
   - Select local region

2. **Enable Secret Manager API**: Activate the Secret Manager API in Google Cloud Console

3. **Configure Application Default Credentials**:
   - Option A: Set up ADC for local development environment
   - Option B: Place service account key file as `service-account.json` in repository root

**Required Environment Variables**:
```bash
GOOGLE_CLOUD_PROJECT_ID=your-project-id
# If using service account file:
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
```

**Sources**: [GETTING_STARTED.md:132-153]()

### PostHog Analytics Integration

PostHog provides product analytics and user behavior tracking.

**Setup Steps**:

1. **Create Account**: Sign up at [PostHog](https://us.posthog.com/signup)
2. **Obtain API Key**: Copy API key from project settings
3. **Get Host URL**: Note PostHog host URL (typically `https://us.posthog.com`)

**Required Environment Variables**:
```bash
POSTHOG_API_KEY=your-api-key
POSTHOG_HOST=https://us.posthog.com
```

**Sources**: [GETTING_STARTED.md:84-89]()

### Storage Configuration

Potpie supports multiple object storage backends for image attachments and file uploads.

| Storage Provider | Environment Variable | Configuration Required |
|-----------------|---------------------|------------------------|
| Google Cloud Storage | `GCS_BUCKET_NAME` | GCP credentials |
| Amazon S3 | `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS credentials |
| Azure Blob Storage | `AZURE_STORAGE_CONTAINER`, `AZURE_STORAGE_CONNECTION_STRING` | Azure credentials |

**Configuration**: The storage backend is selected based on which environment variables are present. The system will automatically use the first available provider.

**Sources**: Architecture diagrams (Diagram 5 - Data Storage Architecture)

### Database Infrastructure

Production deployment requires three separate database systems:

```mermaid
graph TB
    subgraph "Database Services"
        POSTGRES["PostgreSQL<br/>Port: 5432<br/>Database: potpie_production"]
        NEO4J["Neo4j<br/>Port: 7687 (Bolt)<br/>Port: 7474 (HTTP)<br/>Database: neo4j"]
        REDIS["Redis<br/>Port: 6379<br/>Database: 0"]
    end
    
    subgraph "Docker Compose Services"
        POSTGRES_CONTAINER["postgres<br/>service"]
        NEO4J_CONTAINER["neo4j<br/>service"]
        REDIS_CONTAINER["redis<br/>service"]
    end
    
    subgraph "Application Connections"
        SQLALCHEMY["SQLAlchemy ORM<br/>Relational Data"]
        NEO4J_DRIVER["Neo4j Driver<br/>Graph Queries"]
        REDIS_CLIENT["Redis Client<br/>Cache & Streaming"]
    end
    
    POSTGRES_CONTAINER -->|"exposes"| POSTGRES
    NEO4J_CONTAINER -->|"exposes"| NEO4J
    REDIS_CONTAINER -->|"exposes"| REDIS
    
    SQLALCHEMY -->|"connects to"| POSTGRES
    NEO4J_DRIVER -->|"connects to"| NEO4J
    REDIS_CLIENT -->|"connects to"| REDIS
```

**PostgreSQL Configuration**:
```bash
POSTGRES_USER=potpie_user
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=potpie_production
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

**Neo4j Configuration**:
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=secure_password
```

**Redis Configuration**:
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**Sources**: Architecture diagrams (Diagram 5 - Data Storage Architecture)

## Environment Configuration

### Required Environment Variables

The following table lists all environment variables required for production deployment:

| Variable | Purpose | Example Value |
|----------|---------|---------------|
| `ENV` | Deployment environment | `production` |
| `isDevelopmentMode` | Development mode toggle | `disabled` |
| `OPENAI_API_KEY` | OpenAI API authentication | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API authentication | `sk-ant-...` |
| `INFERENCE_MODEL` | Model for knowledge graph generation | `openai/gpt-4o` |
| `CHAT_MODEL` | Model for agent reasoning | `anthropic/claude-3-5-sonnet-20241022` |
| `POSTGRES_USER` | PostgreSQL username | `potpie_user` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `secure_password` |
| `POSTGRES_DB` | PostgreSQL database name | `potpie_production` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | `secure_password` |
| `REDIS_HOST` | Redis host | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `CELERY_BROKER_URL` | Celery message broker | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://localhost:6379/0` |
| `FIREBASE_PROJECT_ID` | Firebase project identifier | `potpie-prod` |
| `FIREBASE_CLIENT_EMAIL` | Firebase service account email | `service@potpie.iam.gserviceaccount.com` |
| `FIREBASE_PRIVATE_KEY` | Firebase service account key | `-----BEGIN PRIVATE KEY-----...` |
| `GITHUB_APP_ID` | GitHub App identifier | `123456` |
| `GITHUB_PRIVATE_KEY` | GitHub App private key | `-----BEGIN RSA PRIVATE KEY-----...` |
| `GH_TOKEN_LIST` | GitHub personal access tokens | `ghp_token1,ghp_token2` |
| `GOOGLE_CLOUD_PROJECT_ID` | GCP project identifier | `potpie-prod` |
| `POSTHOG_API_KEY` | PostHog API key | `phc_...` |
| `POSTHOG_HOST` | PostHog host URL | `https://us.posthog.com` |
| `SENTRY_DSN` | Sentry error tracking DSN | `https://...@sentry.io/...` |
| `GCS_BUCKET_NAME` | Google Cloud Storage bucket | `potpie-storage-prod` |

### Configuration File Setup

1. **Copy Template**:
   ```bash
   cp .env.template .env
   ```

2. **Edit Configuration**: Populate `.env` file with production values for all required variables

3. **Place Credential Files**:
   - `firebase_service_account.json` in repository root
   - `service-account.json` (if using GCP service account) in repository root

**Sources**: [GETTING_STARTED.md:14-21](), [GETTING_STARTED.md:159-160]()

## Deployment Process

### Docker Infrastructure

Potpie uses Docker Compose to orchestrate multiple services. The `start.sh` script manages the complete deployment lifecycle.

```mermaid
graph TB
    START["./start.sh"]
    
    subgraph "Docker Compose Services"
        POSTGRES_SVC["postgres<br/>PostgreSQL 15"]
        NEO4J_SVC["neo4j<br/>Neo4j 5.x"]
        REDIS_SVC["redis<br/>Redis 7.x"]
        APP_SVC["app<br/>FastAPI Application"]
        WORKER_SVC["celery_worker<br/>Celery Background Workers"]
    end
    
    START -->|"docker compose up"| POSTGRES_SVC
    START -->|"docker compose up"| NEO4J_SVC
    START -->|"docker compose up"| REDIS_SVC
    START -->|"docker compose up"| APP_SVC
    START -->|"docker compose up"| WORKER_SVC
    
    APP_SVC -.->|"depends_on"| POSTGRES_SVC
    APP_SVC -.->|"depends_on"| NEO4J_SVC
    APP_SVC -.->|"depends_on"| REDIS_SVC
    WORKER_SVC -.->|"depends_on"| REDIS_SVC
    WORKER_SVC -.->|"depends_on"| POSTGRES_SVC
    WORKER_SVC -.->|"depends_on"| NEO4J_SVC
```

### Deployment Steps

1. **Verify Docker Installation**:
   ```bash
   docker --version
   docker compose --version
   ```

2. **Ensure Environment Configuration**: Verify `.env` file is properly configured with all production values

3. **Verify Credential Files**:
   - Check `firebase_service_account.json` exists
   - Check `service-account.json` exists (if using GCP service account)
   - Verify GitHub private key is formatted

4. **Authenticate to Google Cloud** (if using Application Default Credentials):
   ```bash
   gcloud auth application-default login
   ```

5. **Make Start Script Executable**:
   ```bash
   chmod +x start.sh
   ```

6. **Execute Deployment**:
   ```bash
   ./start.sh
   ```

The `start.sh` script performs the following operations:
- Starts Docker Compose services in dependency order
- Initializes database schemas
- Starts FastAPI application server
- Starts Celery worker processes
- Performs health checks

**Sources**: [GETTING_STARTED.md:156-171]()

### Application Startup Sequence

```mermaid
sequenceDiagram
    participant Script as start.sh
    participant Docker as Docker Compose
    participant Postgres as PostgreSQL
    participant Neo4j as Neo4j
    participant Redis as Redis
    participant App as FastAPI App
    participant Celery as Celery Workers
    
    Script->>Docker: docker compose up -d
    Docker->>Postgres: Start container
    Docker->>Neo4j: Start container
    Docker->>Redis: Start container
    
    Postgres-->>Docker: Ready
    Neo4j-->>Docker: Ready
    Redis-->>Docker: Ready
    
    Docker->>App: Start container
    App->>Postgres: Run migrations
    App->>Neo4j: Verify connection
    App->>Redis: Verify connection
    App->>App: Initialize FastAPI
    App-->>Docker: Ready (port 8000)
    
    Docker->>Celery: Start workers
    Celery->>Redis: Connect to broker
    Celery-->>Docker: Ready
    
    Script-->>Script: Deployment complete
```

**Port Bindings**:
- FastAPI Application: `8000`
- PostgreSQL: `5432`
- Neo4j Bolt: `7687`
- Neo4j HTTP: `7474`
- Redis: `6379`

**Sources**: [GETTING_STARTED.md:161-171]()

## Verification and Health Checks

### Service Health Verification

After deployment, verify all services are operational:

1. **Check Docker Container Status**:
   ```bash
   docker compose ps
   ```
   All services should show status "Up"

2. **Verify API Health**:
   ```bash
   curl http://localhost:8000/health
   ```
   Expected response: `{"status": "healthy"}`

3. **Check PostgreSQL Connection**:
   ```bash
   docker compose exec postgres psql -U potpie_user -d potpie_production -c "SELECT 1;"
   ```

4. **Check Neo4j Connection**:
   Navigate to `http://localhost:7474` and verify browser interface loads

5. **Check Redis Connection**:
   ```bash
   docker compose exec redis redis-cli ping
   ```
   Expected response: `PONG`

6. **Check Celery Workers**:
   ```bash
   docker compose logs celery_worker
   ```
   Look for "ready" messages indicating worker startup

### Application Log Monitoring

Monitor application logs for startup errors or warnings:

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f app
docker compose logs -f celery_worker
```

**Sources**: Deployment process knowledge from architecture diagrams

## Dependency Management

### Python Dependencies

Potpie uses `uv` package manager for dependency management:

1. **Install uv**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Sync Dependencies**:
   ```bash
   uv sync
   ```
   This creates `.venv` directory and installs all dependencies from `pyproject.toml`

3. **Activate Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```

For detailed dependency management information, see [Dependency Management](#11.4).

**Sources**: [GETTING_STARTED.md:5-29]()

## Security Considerations

### Secret Management

Production deployments should use Google Secret Manager for sensitive credentials rather than storing them in `.env` files:

1. **Store Secrets in Secret Manager**:
   - API keys for LLM providers
   - Database credentials
   - Service account keys
   - OAuth client secrets

2. **Application Access**: The `ConfigurationProvider` class automatically fetches secrets from Secret Manager when configured with appropriate GCP credentials

3. **Audit Logging**: All secret access is logged in Google Cloud audit logs

### File Permissions

Ensure credential files have restricted permissions:
```bash
chmod 600 firebase_service_account.json
chmod 600 service-account.json
chmod 600 .env
```

### Network Security

Production deployments should implement:
- TLS/SSL for all external connections
- Firewall rules restricting database access
- VPC/subnet isolation for database services
- API rate limiting and authentication

**Sources**: Architecture diagrams (Diagram 4 - Multi-Provider Authentication Architecture)

## Monitoring and Operations

For comprehensive information on production monitoring, error tracking, distributed tracing, and operational observability, see [Monitoring and Observability](#11.3).

Key production monitoring services:
- **Sentry**: Error tracking and performance monitoring
- **Phoenix**: Distributed tracing for LLM calls and agent execution
- **PostHog**: Product analytics and user behavior tracking
- **Application Logs**: Structured logging via Docker Compose

**Sources**: Architecture diagrams (Overall System Architecture)