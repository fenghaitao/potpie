8.4-Secret Management

# Page: Secret Management

# Secret Management

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [LICENSE](LICENSE)
- [contributing.md](contributing.md)

</details>



This document describes how Potpie securely stores, retrieves, and manages sensitive credentials including LLM provider API keys, OAuth tokens, and cloud service credentials. The system employs a multi-tier secret resolution strategy with Google Cloud Secret Manager for production deployments and environment variable fallbacks for development.

For information about authentication providers and user token management, see [Multi-Provider Authentication](#7.1). For environment configuration, see [Environment Configuration](#8.3).

## Overview

Potpie's secret management system handles three primary types of credentials:

| Secret Type | Storage Method | Usage |
|-------------|---------------|-------|
| **LLM Provider API Keys** | GCP Secret Manager / Environment Variables | OpenAI, Anthropic, OpenRouter authentication ([provider_service.py:653-688]()) |
| **OAuth Tokens** | Encrypted in PostgreSQL | GitHub, SSO provider access tokens ([unified_auth_service.py:254-264]()) |
| **Cloud Credentials** | GCP Secret Manager / Service Account JSON | Firebase, GCP, AWS, Azure authentication |
| **Integration Keys** | GCP Secret Manager / Environment Variables | Firecrawl, PostHog, Slack webhooks |

The system prioritizes security through encryption, implements caching for performance, and provides flexible fallback mechanisms for different deployment environments.

## Secret Resolution Architecture

### Multi-Tier Resolution Flow

The `ProviderService` implements a sophisticated fallback chain for resolving LLM provider API keys:

```mermaid
flowchart TD
    Start["API Key Request<br/>(provider_service.py:653)"] --> ExplicitCheck{"Explicit API Key?<br/>(create_from_config)"}
    
    ExplicitCheck -->|Yes| Return1["Return explicit key"]
    ExplicitCheck -->|No| CacheCheck{"Key in<br/>_api_key_cache?"}
    
    CacheCheck -->|Yes| CacheHit{"Cache value<br/>is None?"}
    CacheHit -->|Yes| ReturnNone1["Return None<br/>(previously checked)"]
    CacheHit -->|No| ReturnCached["Return cached key"]
    
    CacheCheck -->|No| EnvCheck{"LLM_API_KEY<br/>in environment?"}
    EnvCheck -->|Yes| CacheAndReturn1["Cache key<br/>Return env key"]
    
    EnvCheck -->|No| SecretMgrCall["SecretManager.get_secret()<br/>(line 675)"]
    SecretMgrCall --> SecretResult{"Secret found?"}
    
    SecretResult -->|Yes| CacheAndReturn2["Cache key<br/>Return secret"]
    SecretResult -->|404 Error| ProviderEnvCheck{"PROVIDER_API_KEY<br/>in environment?"}
    
    ProviderEnvCheck -->|Yes| CacheAndReturn3["Cache key<br/>Return provider env"]
    ProviderEnvCheck -->|No| CacheNone["Cache None<br/>Return None"]
    
    SecretResult -->|Other Error| RaiseError["Raise Exception"]
```

**Sources:** [app/modules/intelligence/provider/provider_service.py:653-688]()

This resolution strategy ensures:
- **Library Usage Support**: Explicit API keys bypass all lookups ([provider_service.py:656-657]())
- **Performance**: Per-provider caching prevents repeated Secret Manager calls ([provider_service.py:486-488]())
- **Development Flexibility**: Environment variables work without cloud infrastructure
- **Production Security**: Secret Manager integration for credential rotation

### API Key Caching Strategy

```mermaid
graph TB
    subgraph "ProviderService Instance"
        Cache["_api_key_cache: Dict[str, Optional[str]]<br/>(line 488)"]
        ChatConfig["chat_config: LLMProviderConfig"]
        InferenceConfig["inference_config: LLMProviderConfig"]
    end
    
    subgraph "Cache Operations"
        GetKey["_get_api_key(provider)<br/>(line 653)"]
        CheckCache["Check cache[provider]<br/>(line 660)"]
        StoreCache["cache[provider] = key<br/>(line 670, 676, 683)"]
        StoreNone["cache[provider] = None<br/>(line 686)"]
    end
    
    subgraph "External Sources"
        ExplicitKey["Explicit API Key<br/>(create_from_config)"]
        EnvVar["Environment Variables<br/>LLM_API_KEY"]
        SecretMgr["SecretManager.get_secret()"]
        ProviderEnv["PROVIDER_API_KEY env"]
    end
    
    GetKey --> CheckCache
    CheckCache -->|Miss| ExplicitKey
    CheckCache -->|Miss| EnvVar
    CheckCache -->|Miss| SecretMgr
    CheckCache -->|Miss| ProviderEnv
    
    ExplicitKey --> StoreCache
    EnvVar --> StoreCache
    SecretMgr --> StoreCache
    ProviderEnv --> StoreCache
    SecretMgr -->|404| StoreNone
    
    StoreCache --> Cache
    StoreNone --> Cache
    
    Cache --> GetKey
    
    ChatConfig -.uses.-> GetKey
    InferenceConfig -.uses.-> GetKey
```

**Key Implementation Details:**

| Aspect | Implementation |
|--------|---------------|
| **Cache Scope** | Per `ProviderService` instance (per user session) |
| **Cache Key** | Provider name string (e.g., `"openai"`, `"anthropic"`) |
| **Null Caching** | `None` cached to prevent repeated failed lookups ([provider_service.py:686]()) |
| **Invalidation** | No explicit invalidation (session-scoped lifecycle) |

**Sources:** [app/modules/intelligence/provider/provider_service.py:486-488](), [app/modules/intelligence/provider/provider_service.py:653-688]()

## Google Cloud Secret Manager Integration

### SecretManager Service

The `SecretManager` class provides a unified interface to Google Cloud Secret Manager:

```mermaid
graph TB
    subgraph "API Endpoints"
        Router["secret_manager_router<br/>/api/v1"]
        GetSecret["GET /secrets/{provider_name}"]
        SetSecret["POST /secrets"]
        DeleteSecret["DELETE /secrets/{provider_name}"]
    end
    
    subgraph "SecretManager Class"
        GetMethod["get_secret(provider, user_id, db)<br/>Static method"]
        SetMethod["set_secret(provider, api_key, user_id, db)<br/>Static method"]
        DeleteMethod["delete_secret(provider, user_id, db)<br/>Static method"]
        VerifyMethod["verify_secret(provider, api_key)<br/>Static method"]
    end
    
    subgraph "Google Cloud"
        SecretMgrAPI["Secret Manager API<br/>projects/{project}/secrets/{name}"]
        SecretVersion["Secret versions<br/>latest version retrieval"]
    end
    
    subgraph "Database"
        UserPrefs["user_preferences table<br/>User-specific overrides"]
    end
    
    Router --> GetSecret
    Router --> SetSecret
    Router --> DeleteSecret
    
    GetSecret --> GetMethod
    SetSecret --> SetMethod
    DeleteSecret --> DeleteMethod
    
    GetMethod --> UserPrefs
    GetMethod --> SecretMgrAPI
    SetMethod --> SecretMgrAPI
    DeleteMethod --> SecretMgrAPI
    
    GetMethod -.validate.-> VerifyMethod
    SetMethod -.validate.-> VerifyMethod
    
    SecretMgrAPI --> SecretVersion
```

**Configuration Requirements:**

```
Environment Variable          Purpose                           Required For
----------------------------  --------------------------------  ------------------
GCP_PROJECT                   GCP project ID                    Secret Manager API
GOOGLE_APPLICATION_CREDENTIALS Service account JSON path        GCP authentication
```

**Sources:** [app/main.py:27](), [app/main.py:166](), [.env.template:59](), [.env.template:27]()

### Secret Naming Convention

Secrets in GCP Secret Manager follow a predictable naming pattern:

```
Format: {provider_name}-api-key
Examples:
  - openai-api-key
  - anthropic-api-key
  - openrouter-api-key
```

This convention allows `ProviderService` to automatically resolve secrets based on the LLM provider type without additional configuration.

**Sources:** [app/modules/intelligence/provider/provider_service.py:675]()

## Token Encryption System

### OAuth Token Lifecycle

OAuth tokens (GitHub, SSO) are encrypted before storage and decrypted on retrieval using Fernet symmetric encryption:

```mermaid
sequenceDiagram
    participant Client as "Auth Flow"
    participant Service as "UnifiedAuthService"
    participant Encrypt as "encrypt_token()<br/>(token_encryption.py)"
    participant DB as "PostgreSQL<br/>user_auth_providers"
    participant Decrypt as "decrypt_token()<br/>(token_encryption.py)"
    participant Consumer as "GithubService"
    
    Note over Client,Consumer: Token Storage Flow
    
    Client->>Service: add_provider(access_token)
    Service->>Encrypt: encrypt_token(access_token)<br/>(line 256)
    Encrypt->>Encrypt: Get ENCRYPTION_KEY from env
    Encrypt->>Encrypt: Fernet.generate_key() or use key
    Encrypt->>Encrypt: f.encrypt(token.encode())
    Encrypt-->>Service: encrypted_token (bytes)
    Service->>DB: INSERT access_token = encrypted_token<br/>(line 272)
    
    Note over Client,Consumer: Token Retrieval Flow
    
    Consumer->>Service: get_decrypted_access_token(user_id, provider)
    Service->>DB: SELECT access_token FROM user_auth_providers
    DB-->>Service: encrypted_token
    Service->>Decrypt: decrypt_token(encrypted_token)<br/>(line 191)
    Decrypt->>Decrypt: Get ENCRYPTION_KEY from env
    Decrypt->>Decrypt: f.decrypt(encrypted_token)
    
    alt Decryption succeeds
        Decrypt-->>Service: plaintext_token
    else Decryption fails (legacy plaintext)
        Decrypt-->>Service: encrypted_token (as-is)<br/>(backward compatibility)
    end
    
    Service-->>Consumer: token (plaintext)
```

**Sources:** [app/modules/auth/unified_auth_service.py:254-264](), [app/modules/auth/unified_auth_service.py:176-199]()

### Encryption Key Management

```mermaid
graph TB
    subgraph "Key Source"
        EnvKey["ENCRYPTION_KEY<br/>environment variable"]
        GenerateKey["Fernet.generate_key()<br/>if not set"]
    end
    
    subgraph "Token Operations"
        EncryptFunc["encrypt_token(plaintext)<br/>token_encryption.py"]
        DecryptFunc["decrypt_token(ciphertext)<br/>token_encryption.py"]
    end
    
    subgraph "Storage"
        DBField["user_auth_providers.access_token<br/>BYTEA field"]
        DBRefresh["user_auth_providers.refresh_token<br/>BYTEA field"]
    end
    
    subgraph "Consumers"
        UnifiedAuth["UnifiedAuthService<br/>add_provider()"]
        GithubSvc["GithubService<br/>get_github_oauth_token()"]
        AuthRouter["AuthRouter<br/>/signup endpoint"]
    end
    
    EnvKey --> EncryptFunc
    GenerateKey --> EncryptFunc
    EnvKey --> DecryptFunc
    
    UnifiedAuth --> EncryptFunc
    EncryptFunc --> DBField
    EncryptFunc --> DBRefresh
    
    DBField --> DecryptFunc
    DBRefresh --> DecryptFunc
    
    DecryptFunc --> GithubSvc
    DecryptFunc --> AuthRouter
```

**Encryption Specification:**

| Property | Value |
|----------|-------|
| **Algorithm** | Fernet (AES-128 in CBC mode) |
| **Key Format** | 32-byte URL-safe base64-encoded |
| **Storage Format** | Binary (BYTEA in PostgreSQL) |
| **Key Rotation** | Manual (requires re-encryption of existing tokens) |

**Backward Compatibility:**

The system handles legacy plaintext tokens gracefully:

```python
# unified_auth_service.py:189-199
try:
    return decrypt_token(provider.access_token)
except Exception:
    # Token might be plaintext (from before encryption)
    logger.warning(
        f"Failed to decrypt token for user {user_id}, provider {provider_type}. "
        "Assuming plaintext token (backward compatibility)."
    )
    return provider.access_token
```

**Sources:** [app/modules/auth/unified_auth_service.py:189-199](), [app/modules/auth/auth_router.py:211-225]()

## Environment Variable Configuration

### Development Mode Secrets

For local development (`isDevelopmentMode=enabled`), secrets are loaded exclusively from environment variables:

```
# Core LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-v1-...
OLLAMA_API_KEY=ollama  # Placeholder for local Ollama

# GitHub Authentication
GH_TOKEN_LIST=ghp_token1,ghp_token2,...  # PAT pool
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----...

# Cloud Storage
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
GCS_HMAC_ACCESS_KEY=GOOG...
GCS_HMAC_SECRET_KEY=...
AZURE_ACCOUNT_KEY=...

# Integrations
FIRECRAWL_API_KEY=fc-...
POSTHOG_API_KEY=phc_...
RESEND_API_KEY=re_...

# Token Encryption
ENCRYPTION_KEY=fernet-key-base64...
```

**Sources:** [.env.template:1-73]()

### Provider-Specific Key Resolution

The `ProviderService` supports both generic and provider-specific environment variables:

```mermaid
flowchart LR
    Request["LLM API Call"] --> GetKey["_get_api_key('anthropic')"]
    
    GetKey --> CheckGeneric{"LLM_API_KEY<br/>set?"}
    CheckGeneric -->|Yes| UseGeneric["Use LLM_API_KEY<br/>(line 668)"]
    CheckGeneric -->|No| CheckProvider{"ANTHROPIC_API_KEY<br/>set?"}
    CheckProvider -->|Yes| UseProvider["Use ANTHROPIC_API_KEY<br/>(line 681)"]
    CheckProvider -->|No| Fail["Return None"]
    
    UseGeneric --> Call["Make LLM API Call"]
    UseProvider --> Call
```

This dual-level approach allows:
- **Single key development**: Set `LLM_API_KEY` for any provider
- **Multi-provider production**: Set provider-specific keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)

**Sources:** [app/modules/intelligence/provider/provider_service.py:668-684]()

## Production Deployment Patterns

### Google Cloud Secret Manager Setup

```mermaid
graph TB
    subgraph "GCP Project"
        Secrets["Secret Manager Secrets"]
        ServiceAccount["Service Account<br/>secret-accessor role"]
        Credentials["credentials.json<br/>service account key"]
    end
    
    subgraph "Application Server"
        EnvVar["GOOGLE_APPLICATION_CREDENTIALS<br/>=/path/to/credentials.json"]
        GCPProject["GCP_PROJECT=project-id"]
        SecretMgr["SecretManager Service"]
    end
    
    subgraph "Secret Types"
        OpenAI["openai-api-key"]
        Anthropic["anthropic-api-key"]
        OpenRouter["openrouter-api-key"]
        Firebase["firebase-admin-credentials"]
    end
    
    Credentials --> ServiceAccount
    ServiceAccount --> Secrets
    
    EnvVar --> SecretMgr
    GCPProject --> SecretMgr
    SecretMgr --> Secrets
    
    Secrets --> OpenAI
    Secrets --> Anthropic
    Secrets --> OpenRouter
    Secrets --> Firebase
```

**Required IAM Permissions:**

```yaml
roles/secretmanager.secretAccessor:
  - secretmanager.versions.access
  - secretmanager.versions.get
  - secretmanager.secrets.get
```

**Sources:** [.env.template:59](), [.env.template:27]()

### Database Token Storage Schema

```mermaid
erDiagram
    user_auth_providers {
        uuid id PK
        string user_id FK
        string provider_type
        string provider_uid
        bytea access_token "Encrypted Fernet"
        bytea refresh_token "Encrypted Fernet"
        timestamp token_expires_at
        jsonb provider_data
        boolean is_primary
        timestamp linked_at
        timestamp last_used_at
    }
    
    users {
        string uid PK
        string email
        jsonb provider_info "Legacy token storage"
    }
    
    user_auth_providers ||--o{ users : "belongs to"
```

**Token Encryption Properties:**

| Column | Type | Encryption | Backward Compatibility |
|--------|------|-----------|----------------------|
| `access_token` | `BYTEA` | Fernet symmetric | Handles plaintext fallback |
| `refresh_token` | `BYTEA` | Fernet symmetric | Handles plaintext fallback |
| `provider_data` | `JSONB` | None | Plain metadata only |

**Sources:** [app/modules/auth/unified_auth_service.py:254-280]()

## Security Considerations

### Secret Rotation

| Secret Type | Rotation Method | Impact |
|-------------|----------------|--------|
| **LLM API Keys** | Update GCP Secret Manager version | Cached keys cleared on next request |
| **OAuth Tokens** | Refresh token flow (automatic) | No manual intervention needed |
| **Encryption Key** | Manual re-encryption required | All tokens must be decrypted/re-encrypted |
| **Service Account Keys** | GCP credential rotation | Requires pod/server restart |

### Cache Security

The `_api_key_cache` in `ProviderService` has important security properties:

- **Scope**: Per-instance (per-request lifecycle for API calls)
- **Lifetime**: Request duration only
- **Memory**: Not persisted to disk
- **Isolation**: Each user gets separate `ProviderService` instance

**Sources:** [app/modules/intelligence/provider/provider_service.py:481-488]()

### Logging and Audit

Sensitive values are **not** logged:

```python
# provider_service.py never logs actual keys
logger.info(f"Using token from GH_TOKEN_LIST as fallback")  # Safe
# Not: logger.info(f"Token: {api_key}")  # Never done
```

OAuth token operations are audited in `auth_audit_log` table via `UnifiedAuthService._log_auth_event()` without logging token values.

**Sources:** [app/modules/auth/unified_auth_service.py:296-304]()

## Usage Examples

### Using Secrets in Development

```bash
# .env file for local development
isDevelopmentMode=enabled
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

### Library Usage with Explicit Keys

For library integration, bypass all secret resolution:

```python
# Using create_from_config with explicit API key
service = ProviderService.create_from_config(
    db=db,
    user_id="user-123",
    provider="openai",
    api_key="sk-proj-explicit-key",  # Direct injection
    chat_model="openai/gpt-4o"
)
```

**Sources:** [app/modules/intelligence/provider/provider_service.py:511-587]()

### Retrieving Decrypted GitHub Tokens

```python
# In GithubService
github_oauth_token = self.get_github_oauth_token(user_id)

# Internally uses UnifiedAuthService
from app.modules.auth.unified_auth_service import UnifiedAuthService
unified_auth = UnifiedAuthService(db)
token = unified_auth.get_decrypted_access_token(
    user_id=user_id,
    provider_type="firebase_github"
)
```

**Sources:** [app/modules/code_provider/github/github_service.py:184-247](), [app/modules/auth/unified_auth_service.py:176-199]()

## Error Handling

### Secret Manager Failures

```mermaid
flowchart TD
    GetSecret["SecretManager.get_secret()"] --> TryCall["Try API Call"]
    TryCall --> Success["Return secret value"]
    TryCall --> Error404["404 Error<br/>(secret not found)"]
    TryCall --> OtherError["Other Exceptions"]
    
    Error404 --> CheckEnv["Check PROVIDER_API_KEY<br/>environment variable"]
    CheckEnv --> EnvFound["Return env value<br/>Cache result"]
    CheckEnv --> NotFound["Return None<br/>Cache None"]
    
    OtherError --> Raise["Raise Exception<br/>(don't cache)"]
```

**Sources:** [app/modules/intelligence/provider/provider_service.py:674-688]()

### Token Decryption Failures

```python
# Backward compatibility handling
try:
    decrypted = decrypt_token(encrypted_token)
except Exception:
    # Token might be plaintext from before encryption was added
    logger.warning("Failed to decrypt, assuming plaintext (backward compatibility)")
    decrypted = encrypted_token  # Use as-is
```

This pattern allows seamless migration from plaintext to encrypted token storage without requiring database migration.

**Sources:** [app/modules/auth/unified_auth_service.py:189-199]()

## Related Systems

- **Configuration Management** - See [Configuration Provider](#8.1) for how secrets integrate with overall configuration
- **Authentication** - See [Multi-Provider Authentication](#7.1) for how OAuth tokens are acquired
- **Provider Service** - See [Provider Service (LLM Abstraction)](#2.1) for how API keys are consumed
- **Media Storage** - See [Media Service and Storage](#8.2) for cloud storage credential usage