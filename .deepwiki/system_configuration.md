1.4-System Configuration

# Page: System Configuration

# System Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [LICENSE](LICENSE)
- [app/core/config_provider.py](app/core/config_provider.py)
- [app/modules/code_provider/code_provider_service.py](app/modules/code_provider/code_provider_service.py)
- [app/modules/code_provider/local_repo/local_repo_service.py](app/modules/code_provider/local_repo/local_repo_service.py)
- [app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py](app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py)
- [app/modules/parsing/graph_construction/parsing_controller.py](app/modules/parsing/graph_construction/parsing_controller.py)
- [contributing.md](contributing.md)

</details>



## Purpose and Scope

This document explains Potpie's configuration system, including environment variables, configuration cascades, and deployment settings for development and production environments. The system is built around the `ConfigProvider` singleton that centralizes all configuration access across the application.

For specific authentication configuration details, see [Multi-Provider Authentication](#7.1). For media storage setup, see [Media Service and Storage](#8.2). For agent and LLM provider configuration, see [Provider Service](#2.1).

---

## Configuration Provider Architecture

### The ConfigProvider Singleton

The `ConfigProvider` class [app/core/config_provider.py:19-246]() serves as the central configuration hub for the entire application. It implements a singleton pattern where a single instance (`config_provider`) is instantiated at module load time and imported throughout the codebase.

```mermaid
graph TB
    subgraph "Configuration Sources"
        EnvFile[".env File<br/>dotenv.load_dotenv()"]
        EnvVars["Environment Variables<br/>os.getenv()"]
        Override["Runtime Overrides<br/>set_neo4j_override()"]
    end
    
    subgraph "ConfigProvider Singleton"
        Instance["config_provider<br/>app/core/config_provider.py:245"]
        Neo4j["Neo4j Config<br/>uri, username, password"]
        Redis["Redis URL<br/>get_redis_url()"]
        GitHub["GitHub Config<br/>GITHUB_PRIVATE_KEY, GITHUB_APP_ID"]
        Storage["Storage Config<br/>GCS/S3/Azure"]
        Features["Feature Flags<br/>isDevelopmentMode<br/>isMultimodalEnabled"]
        CodeProvider["Code Provider Config<br/>CODE_PROVIDER<br/>CODE_PROVIDER_BASE_URL"]
    end
    
    subgraph "Service Consumers"
        MediaSvc["MediaService<br/>line 49"]
        ParseSvc["ParsingService<br/>Neo4j connection"]
        CodeProvSvc["CodeProviderService<br/>provider type detection"]
        ProviderSvc["ProviderService<br/>API keys"]
        AuthSvc["UnifiedAuthService<br/>GitHub credentials"]
    end
    
    EnvFile --> EnvVars
    EnvVars --> Instance
    Override --> Neo4j
    
    Instance --> Neo4j
    Instance --> Redis
    Instance --> GitHub
    Instance --> Storage
    Instance --> Features
    Instance --> CodeProvider
    
    Neo4j --> ParseSvc
    Redis --> ParseSvc
    Storage --> MediaSvc
    Features --> MediaSvc
    GitHub --> AuthSvc
    CodeProvider --> CodeProvSvc
    
    style Instance fill:#f9f,stroke:#333,stroke-width:4px
```

**Sources:** [app/core/config_provider.py:19-246](), [app/modules/media/media_service.py:47-75]()

### Neo4j Configuration with Runtime Overrides

The `ConfigProvider` supports runtime Neo4j configuration overrides to enable library usage without environment variables. This is critical for the PotpieRuntime library mode.

| Method | Purpose | Usage Context |
|--------|---------|---------------|
| `set_neo4j_override(config)` | Set class-level Neo4j config override | Library initialization |
| `get_neo4j_config()` | Get Neo4j config, preferring override if set | All Neo4j connections |
| `clear_neo4j_override()` | Clear the override | Library cleanup |

```mermaid
graph LR
    subgraph "Standard Mode"
        Env1["Environment Variables"] --> GetConfig1["get_neo4j_config()"]
        GetConfig1 --> Neo1["Neo4j Connection"]
    end
    
    subgraph "Library Mode"
        Override["set_neo4j_override()<br/>class method"] --> ClassVar["_neo4j_override<br/>class variable"]
        ClassVar --> GetConfig2["get_neo4j_config()"]
        GetConfig2 --> Neo2["Neo4j Connection"]
    end
    
    GetConfig1 -.checks.-> ClassVar
    GetConfig2 -.checks.-> ClassVar
```

**Sources:** [app/core/config_provider.py:52-73]()

---

## Environment Variable Reference

### Core Infrastructure

| Variable | Purpose | Required | Default | Example |
|----------|---------|----------|---------|---------|
| `ENV` | Environment name (development/staging/production) | No | - | `development` |
| `isDevelopmentMode` | Enable development mode with minimal dependencies | No | `disabled` | `enabled` |
| `NEO4J_URI` | Neo4j database URI | Yes | - | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | Neo4j authentication username | Yes | - | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j authentication password | Yes | - | `password123` |
| `REDISHOST` | Redis server hostname | No | `localhost` | `redis.example.com` |
| `REDISPORT` | Redis server port | No | `6379` | `6379` |
| `REDISUSER` | Redis authentication username | No | - | `redisuser` |
| `REDISPASSWORD` | Redis authentication password | No | - | `redispass` |
| `POSTGRES_URL` | PostgreSQL connection URL | Yes | - | `postgresql://user:pass@host/db` |

**Sources:** [app/core/config_provider.py:22-27, 142-152](), [GETTING_STARTED.md:14-21]()

### GitHub Integration

| Variable | Purpose | Required | Default |
|----------|---------|----------|---------|
| `GITHUB_APP_ID` | GitHub App ID for authentication | Production only | - |
| `GITHUB_PRIVATE_KEY` | GitHub App private key (formatted) | Production only | - |
| `GH_TOKEN_LIST` | Comma-separated list of PATs for rate limit distribution | No | - |
| `CODE_PROVIDER_TOKEN` | Primary code provider PAT | No | - |
| `CODE_PROVIDER_TOKEN_POOL` | Comma-separated PAT pool for fallback | No | - |

The GitHub private key must be formatted using the provided `format_pem.sh` script [GETTING_STARTED.md:110-117]() to ensure proper line break encoding for environment variables.

**Sources:** [app/core/config_provider.py:28, 75-80, 227-234](), [GETTING_STARTED.md:92-120]()

### LLM Provider Configuration

| Variable | Purpose | Required | Example |
|----------|---------|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key | If using OpenAI | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key | If using Claude | `sk-ant-...` |
| `{PROVIDER}_API_KEY` | Generic provider API key pattern | Provider-specific | - |
| `INFERENCE_MODEL` | Model for docstring generation and embeddings | Yes | `ollama_chat/qwen2.5-coder:7b` |
| `CHAT_MODEL` | Model for agent reasoning and chat | Yes | `openrouter/deepseek/deepseek-chat` |

Model names follow the litellm format: `provider/model_name`. See [Provider Service](#2.1) for details.

**Sources:** [GETTING_STARTED.md:20, 31-46]()

### Object Storage Configuration

The system supports three object storage providers with automatic detection:

| Variable | Purpose | Provider | Required |
|----------|---------|----------|----------|
| `OBJECT_STORAGE_PROVIDER` | Explicit provider selection (`s3`/`gcs`/`azure`/`auto`) | All | No (default: `auto`) |
| `GCS_PROJECT_ID` | Google Cloud project ID | GCS | Yes for GCS |
| `GCS_BUCKET_NAME` | GCS bucket name | GCS | Yes for GCS |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | GCS | Yes for GCS |
| `S3_BUCKET_NAME` | S3 bucket name | S3 | Yes for S3 |
| `AWS_REGION` | AWS region | S3 | Yes for S3 |
| `AWS_ACCESS_KEY_ID` | AWS access key | S3 | Yes for S3 |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | S3 | Yes for S3 |
| `AZURE_STORAGE_ACCOUNT_NAME` | Azure storage account | Azure | Yes for Azure |
| `AZURE_STORAGE_ACCOUNT_KEY` | Azure account key | Azure | Yes for Azure |
| `AZURE_CONTAINER_NAME` | Azure container name | Azure | Yes for Azure |

**Sources:** [app/core/config_provider.py:31-44](), [app/modules/media/media_service.py:56-71]()

### Code Provider Configuration

| Variable | Purpose | Default | Example |
|----------|---------|---------|---------|
| `CODE_PROVIDER` | Provider type (`github`/`gitbucket`/`local`) | `github` | `gitbucket` |
| `CODE_PROVIDER_BASE_URL` | Base URL for self-hosted instances | - | `https://git.company.com` |
| `CODE_PROVIDER_USERNAME` | Username for Basic Auth | - | `admin` |
| `CODE_PROVIDER_PASSWORD` | Password for Basic Auth | - | `password` |

**Sources:** [app/core/config_provider.py:219-242]()

### Feature Flags

| Variable | Purpose | Values | Default |
|----------|---------|--------|---------|
| `isMultimodalEnabled` | Enable image upload and multimodal LLM features | `enabled`/`disabled`/`auto` | `auto` |
| `REPO_MANAGER_ENABLED` | Enable local repository caching in `.repos` directory | `true`/`false` | `false` |

The `auto` mode for `isMultimodalEnabled` automatically enables the feature if object storage credentials are detected [app/core/config_provider.py:157-172]().

**Sources:** [app/core/config_provider.py:29-30, 157-172](), [app/modules/code_provider/code_provider_service.py:162-164]()

### Redis Stream Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDIS_STREAM_TTL_SECS` | Stream message TTL in seconds | `900` (15 minutes) |
| `REDIS_STREAM_MAX_LEN` | Maximum messages per stream | `1000` |
| `REDIS_STREAM_PREFIX` | Stream key prefix | `chat:stream` |

**Sources:** [app/core/config_provider.py:207-217]()

---

## Configuration Cascade and Precedence

### Neo4j Configuration Priority

```mermaid
graph TD
    Check{"Neo4j config<br/>requested"}
    Override{"_neo4j_override<br/>set?"}
    EnvVars["Environment Variables<br/>NEO4J_URI, NEO4J_USERNAME<br/>NEO4J_PASSWORD"]
    ReturnOverride["Return override config"]
    ReturnEnv["Return env config"]
    
    Check --> Override
    Override -->|Yes| ReturnOverride
    Override -->|No| EnvVars
    EnvVars --> ReturnEnv
```

This precedence enables library mode where Neo4j configuration can be injected programmatically without modifying environment variables.

**Sources:** [app/core/config_provider.py:69-73]()

### Storage Provider Auto-Detection

The storage provider selection follows this precedence:

```mermaid
graph TD
    Start["get_object_storage_descriptor()"]
    ExplicitCheck{"OBJECT_STORAGE_PROVIDER<br/>!= 'auto'?"}
    ExplicitReady{"Explicit provider<br/>credentials ready?"}
    UseExplicit["Use explicit provider"]
    AutoDetect["Auto-detect providers"]
    CheckS3{"S3 credentials<br/>present?"}
    CheckGCS{"GCS credentials<br/>present?"}
    CheckAzure{"Azure credentials<br/>present?"}
    UseS3["Use S3"]
    UseGCS["Use GCS"]
    UseAzure["Use Azure"]
    UseNone["Use 'none'<br/>(multimodal disabled)"]
    
    Start --> ExplicitCheck
    ExplicitCheck -->|Yes| ExplicitReady
    ExplicitReady -->|Yes| UseExplicit
    ExplicitReady -->|No| UseNone
    ExplicitCheck -->|No| AutoDetect
    AutoDetect --> CheckS3
    CheckS3 -->|Yes| UseS3
    CheckS3 -->|No| CheckGCS
    CheckGCS -->|Yes| UseGCS
    CheckGCS -->|No| CheckAzure
    CheckAzure -->|Yes| UseAzure
    CheckAzure -->|No| UseNone
```

Each provider has a corresponding strategy class that implements the `is_ready()` method to check if all required credentials are present:

| Strategy Class | Checks For |
|----------------|------------|
| `S3StorageStrategy` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `AWS_REGION` |
| `GCSStorageStrategy` | `GCS_PROJECT_ID`, `GCS_BUCKET_NAME`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `AzureStorageStrategy` | `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_ACCOUNT_KEY`, `AZURE_CONTAINER_NAME` |

**Sources:** [app/core/config_provider.py:174-205]()

### Redis URL Construction

Redis URL construction follows this logic [app/core/config_provider.py:142-152]():

```python
if REDISUSER and REDISPASSWORD:
    redis_url = f"redis://{REDISUSER}:{REDISPASSWORD}@{REDISHOST}:{REDISPORT}/0"
else:
    redis_url = f"redis://{REDISHOST}:{REDISPORT}/0"
```

This enables both authenticated and unauthenticated Redis connections.

**Sources:** [app/core/config_provider.py:142-152]()

---

## Development Mode Configuration

### Development Mode Overview

Development mode (`isDevelopmentMode=enabled`) allows running Potpie with minimal external dependencies. This mode is designed for local development, testing, and contributions.

```mermaid
graph TB
    subgraph "Production Requirements"
        FirebaseProd["Firebase Auth"]
        GitHubProd["GitHub App"]
        PostHogProd["PostHog Analytics"]
        GCPProd["GCP Secret Manager"]
        StorageProd["Object Storage<br/>(S3/GCS/Azure)"]
    end
    
    subgraph "Development Mode"
        AuthBypass["Authentication Bypass<br/>defaultUsername"]
        LocalGH["Local GitHub PAT<br/>(optional)"]
        NoAnalytics["Analytics Disabled"]
        EnvSecrets["Environment Variable<br/>Secrets"]
        NoStorage["No Object Storage<br/>(multimodal disabled)"]
    end
    
    subgraph "Core Requirements (Both Modes)"
        Neo4jCore["Neo4j"]
        RedisCore["Redis"]
        PostgresCore["PostgreSQL"]
        LLMCore["LLM Provider<br/>(can be Ollama)"]
    end
    
    FirebaseProd -.replaces.-> AuthBypass
    GitHubProd -.replaces.-> LocalGH
    PostHogProd -.replaces.-> NoAnalytics
    GCPProd -.replaces.-> EnvSecrets
    StorageProd -.replaces.-> NoStorage
```

**Sources:** [GETTING_STARTED.md:1-61](), [contributing.md:116-126]()

### Minimal Development Environment

The minimal `.env` configuration for development mode [GETTING_STARTED.md:16-21]():

```bash
isDevelopmentMode=enabled
ENV=development
OPENAI_API_KEY=<your-openai-key>
# Or use local models:
INFERENCE_MODEL=ollama_chat/qwen2.5-coder:7b
CHAT_MODEL=ollama_chat/qwen2.5-coder:7b
```

**Sources:** [GETTING_STARTED.md:16-46]()

### Development vs ENV Distinction

The `ENV` and `isDevelopmentMode` variables serve different purposes [contributing.md:116-126]():

| Variable | Purpose | Effect |
|----------|---------|--------|
| `ENV` | Deployment environment (development/staging/production) | Controls which config files to load, logging levels, error handling |
| `isDevelopmentMode` | Dependency bypass flag | Disables Firebase, GitHub App, PostHog, GCP Secret Manager requirements |

Setting `ENV=development` still requires all production dependencies (Firebase, GitHub App, etc.) but runs the backend locally. Setting `isDevelopmentMode=enabled` removes these dependencies entirely.

**Sources:** [contributing.md:116-126](), [app/core/config_provider.py:29, 154-155]()

---

## Production Deployment Configuration

### Required Production Services

```mermaid
graph TB
    subgraph "Authentication"
        Firebase["Firebase Auth<br/>firebase_service_account.json"]
        GitHubApp["GitHub App<br/>GITHUB_APP_ID<br/>GITHUB_PRIVATE_KEY"]
    end
    
    subgraph "Secret Management"
        GCPSecrets["GCP Secret Manager<br/>Application Default Credentials"]
    end
    
    subgraph "Analytics & Monitoring"
        PostHog["PostHog Analytics<br/>POSTHOG_API_KEY<br/>POSTHOG_HOST"]
        Phoenix["Phoenix Tracing<br/>(optional)"]
        Sentry["Sentry Error Tracking<br/>(optional)"]
    end
    
    subgraph "Storage"
        ObjectStorage["Object Storage<br/>S3/GCS/Azure"]
    end
    
    subgraph "Code Access"
        GitHubAuth["GitHub Authentication<br/>App + PAT Pool"]
    end
    
    Firebase --> Auth[Authentication System]
    GitHubApp --> Auth
    GCPSecrets --> APIKeys[API Key Storage]
    PostHog --> Analytics[Usage Analytics]
    Phoenix --> Observability[LLM Observability]
    Sentry --> Observability
    ObjectStorage --> Multimodal[Multimodal Features]
    GitHubAuth --> RepoAccess[Repository Access]
```

**Sources:** [GETTING_STARTED.md:63-153]()

### Firebase Setup

Firebase configuration requires:

1. Service account key at `firebase_service_account.json` in project root [GETTING_STARTED.md:75-76]()
2. Firebase app configuration keys in `.env` [GETTING_STARTED.md:79-80]()
3. GitHub OAuth app for Firebase authentication [GETTING_STARTED.md:123-128]()

**Sources:** [GETTING_STARTED.md:67-82, 123-128]()

### GitHub App Configuration

GitHub App setup [GETTING_STARTED.md:92-120]():

**Required Permissions:**
- **Repository Permissions:**
  - Contents: Read Only
  - Metadata: Read Only
  - Pull Requests: Read and Write
  - Secrets: Read Only
  - Webhook: Read Only
- **Organization Permissions:**
  - Members: Read Only
- **Account Permissions:**
  - Email Address: Read Only

The private key must be formatted using `format_pem.sh` before adding to environment variables [GETTING_STARTED.md:110-117]().

**Sources:** [GETTING_STARTED.md:92-120]()

### Google Cloud Secret Manager

Secret Manager setup [GETTING_STARTED.md:132-152]():

1. Install and initialize gcloud CLI: `gcloud init`
2. Enable Secret Manager API in GCP project
3. Configure Application Default Credentials (ADC):
   - For local development: `gcloud auth application-default login`
   - For production: Place service account key in `service-account.json`

The system falls back to environment variables if Secret Manager is unavailable.

**Sources:** [GETTING_STARTED.md:132-152]()

---

## Storage Strategy Pattern

### Strategy Architecture

The storage configuration uses the Strategy pattern to abstract different cloud providers behind a common interface:

```mermaid
classDiagram
    class ConfigProvider {
        +object_storage_provider: str
        +_storage_strategies: dict
        +get_object_storage_descriptor() dict
        +_detect_object_storage_dependencies() tuple
    }
    
    class StorageStrategy {
        <<interface>>
        +is_ready(config_provider) bool
        +get_descriptor(config_provider) dict
    }
    
    class S3StorageStrategy {
        +is_ready(config_provider) bool
        +get_descriptor(config_provider) dict
    }
    
    class GCSStorageStrategy {
        +is_ready(config_provider) bool
        +get_descriptor(config_provider) dict
    }
    
    class AzureStorageStrategy {
        +is_ready(config_provider) bool
        +get_descriptor(config_provider) dict
    }
    
    class MediaService {
        -s3_client: boto3.client
        -bucket_name: str
        -storage_provider: StorageProvider
        +_initialize_storage_client()
    }
    
    ConfigProvider --> StorageStrategy
    StorageStrategy <|-- S3StorageStrategy
    StorageStrategy <|-- GCSStorageStrategy
    StorageStrategy <|-- AzureStorageStrategy
    ConfigProvider --> MediaService
```

**Sources:** [app/core/config_provider.py:5-10, 45-50, 174-188]()

### Storage Descriptor Format

Each strategy returns a descriptor dictionary with standardized structure:

```python
{
    "provider": "s3" | "gcs" | "azure",
    "bucket_name": str,
    "client_kwargs": {
        # Provider-specific boto3 client initialization parameters
        # S3: aws_access_key_id, aws_secret_access_key, region_name
        # GCS: aws_access_key_id, aws_secret_access_key, endpoint_url
        # Azure: aws_access_key_id, aws_secret_access_key, endpoint_url
    }
}
```

The `MediaService` uses this descriptor to initialize a boto3 client that works uniformly across all three providers [app/modules/media/media_service.py:77-90]().

**Sources:** [app/core/config_provider.py:178-188](), [app/modules/media/media_service.py:77-90]()

### boto3 Client Initialization

```mermaid
sequenceDiagram
    participant MS as MediaService
    participant CP as ConfigProvider
    participant Strategy as StorageStrategy
    participant Boto3 as boto3.client
    
    MS->>CP: get_object_storage_descriptor()
    CP->>Strategy: is_ready(config_provider)
    Strategy-->>CP: True/False
    CP->>Strategy: get_descriptor(config_provider)
    Strategy-->>CP: descriptor dict
    CP-->>MS: descriptor
    MS->>Boto3: boto3.client("s3", **client_kwargs)
    Boto3-->>MS: s3_client
    MS->>Boto3: head_bucket(Bucket=bucket_name)
    Boto3-->>MS: success/failure
```

All three providers (S3, GCS, Azure) use the boto3 S3 client with different endpoints and credentials [app/modules/media/media_service.py:82-90]().

**Sources:** [app/modules/media/media_service.py:77-90]()

---

## Configuration Consumption Patterns

### Service-Level Configuration Access

Services access configuration through direct import of the singleton:

```python
from app.core.config_provider import config_provider

class SomeService:
    def __init__(self):
        self.neo4j_config = config_provider.get_neo4j_config()
        self.is_dev_mode = config_provider.get_is_development_mode()
```

**Sources:** [app/modules/media/media_service.py:13, 49](), [app/modules/code_provider/code_provider_service.py:162]()

### Configuration in Tools

Tools access configuration for operational decisions:

```python
# Checking if multimodal is enabled
is_multimodal_enabled = config_provider.get_is_multimodal_enabled()

# Getting storage backend type
backend = config_provider.get_media_storage_backend()

# Getting code provider configuration
provider_type = config_provider.get_code_provider_type()
base_url = config_provider.get_code_provider_base_url()
```

**Sources:** [app/core/config_provider.py:157-176, 219-242]()

### Demo Repository Configuration

The system maintains a hardcoded list of demo repositories [app/core/config_provider.py:82-140]():

```python
demo_repos = config_provider.get_demo_repo_list()
# Returns list of dicts with: id, name, full_name, private, url, owner
```

These repositories receive optimized graph duplication instead of full parsing. See [Demo Project Duplication](#4.5) for details.

**Sources:** [app/core/config_provider.py:82-140]()

---

## Configuration Validation and Error Handling

### Missing Configuration Detection

The system validates configuration at service initialization:

```mermaid
graph TD
    ServiceInit["Service Initialization"]
    CheckMultimodal{"isMultimodalEnabled<br/>check"}
    CheckStorage{"Storage credentials<br/>present?"}
    InitClient["Initialize boto3 client"]
    TestBucket["Test bucket access<br/>head_bucket()"]
    Success["Service ready"]
    DisableFeature["Multimodal disabled"]
    RaiseError["Raise MediaServiceError"]
    
    ServiceInit --> CheckMultimodal
    CheckMultimodal -->|enabled| CheckStorage
    CheckMultimodal -->|disabled/auto| CheckStorage
    CheckStorage -->|Yes| InitClient
    CheckStorage -->|No + auto| DisableFeature
    CheckStorage -->|No + enabled| RaiseError
    InitClient --> TestBucket
    TestBucket -->|Success| Success
    TestBucket -->|Failure| RaiseError
```

**Sources:** [app/modules/media/media_service.py:47-90](), [app/core/config_provider.py:15-16, 183-184]()

### GitHub Configuration Validation

The system provides a method to check GitHub configuration completeness:

```python
is_configured = config_provider.is_github_configured()
# Returns True if both GITHUB_PRIVATE_KEY and GITHUB_APP_ID are set
```

This is used to determine whether to use GitHub App authentication or fall back to PAT authentication.

**Sources:** [app/core/config_provider.py:78-80]()

### Configuration Error Types

| Error Class | Raised When | Recovery |
|-------------|-------------|----------|
| `MediaServiceConfigError` | Object storage configuration invalid | Fix credentials or set `isMultimodalEnabled=disabled` |
| `HTTPException(404)` | Project not found in database | Verify project_id |
| `HTTPException(400)` | Missing required configuration | Add missing environment variables |

**Sources:** [app/core/config_provider.py:15-16](), [app/modules/media/media_service.py:25-28, 63-65]()