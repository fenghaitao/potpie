6.3-Multi-Provider Repository Access

# Page: Multi-Provider Repository Access

# Multi-Provider Repository Access

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/core/config_provider.py](app/core/config_provider.py)
- [app/modules/code_provider/code_provider_service.py](app/modules/code_provider/code_provider_service.py)
- [app/modules/code_provider/local_repo/local_repo_service.py](app/modules/code_provider/local_repo/local_repo_service.py)
- [app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py](app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py)
- [app/modules/parsing/graph_construction/parsing_controller.py](app/modules/parsing/graph_construction/parsing_controller.py)

</details>



## Purpose and Scope

This document explains Potpie's support for accessing repositories from multiple code hosting providers, including GitHub, self-hosted Git servers (GitBucket, GitLab), and local file systems. It covers the provider abstraction layer, authentication strategies, and the fallback chain that ensures robust repository access.

The system uses a unified interface (`ICodeProvider`) that abstracts provider-specific details, enabling seamless integration with different code hosts without changing downstream code. The `CodeProviderFactory` handles provider selection and instantiation, while `ProviderWrapper` manages authentication fallback.

For GitHub-specific authentication (OAuth, App Auth, token pools), see [GitHub Integration](#6.2). For project lifecycle management, see [Project Service](#6.1). For how repositories are parsed into knowledge graphs, see [Knowledge Graph Construction](#4).

---

## Provider Abstraction Architecture

Potpie uses a provider abstraction layer to support multiple code hosting platforms through a unified interface.

### Provider Factory and Selection

**Title: Provider Selection and Instantiation Flow**

```mermaid
graph TB
    Request["Repository Access Request<br/>repo_name parameter"]
    
    Factory["CodeProviderFactory.create_provider_with_fallback()"]
    
    subgraph "Configuration Detection"
        EnvCheck["Read CODE_PROVIDER<br/>environment variable"]
        PathCheck["Detect Local Path<br/>os.path checks"]
    end
    
    subgraph "Provider Types"
        GitHub["GitHubProvider<br/>github.com"]
        GitBucket["GitBucketProvider<br/>Self-hosted"]
        Local["LocalProvider<br/>File system"]
    end
    
    subgraph "Authentication Chain (GitHub)"
        AppAuth["GitHub App<br/>Installation Token"]
        PATPool["PAT Token Pool<br/>Multiple tokens"]
        SinglePAT["Single PAT<br/>CODE_PROVIDER_TOKEN"]
        Unauth["Unauthenticated<br/>Public repos only"]
    end
    
    subgraph "Integration Layers"
        RepoManager["RepoManager<br/>Local caching in .repos"]
        RepoWrapper["RepoManagerCodeProviderWrapper<br/>Transparent local fallback"]
    end
    
    Wrapper["ProviderWrapper<br/>Unified Interface"]
    Consumer["Downstream Services<br/>ParsingService, ToolService"]
    
    Request --> Factory
    Factory --> EnvCheck
    Factory --> PathCheck
    
    EnvCheck --> GitHub
    EnvCheck --> GitBucket
    PathCheck --> Local
    
    GitHub --> AppAuth
    GitHub --> PATPool
    GitHub --> SinglePAT
    GitHub --> Unauth
    
    GitBucket --> SinglePAT
    Local --> Wrapper
    
    AppAuth --> RepoManager
    PATPool --> RepoManager
    SinglePAT --> RepoManager
    Unauth --> RepoManager
    
    RepoManager --> RepoWrapper
    RepoWrapper --> Wrapper
    
    Wrapper --> Consumer
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:143-187]()
- [app/modules/code_provider/code_provider_service.py:259-262]()
- [app/core/config_provider.py:219-243]()

### Provider Configuration

The system determines which provider to use based on environment variables:

| Environment Variable | Purpose | Example |
|---------------------|---------|---------|
| `CODE_PROVIDER` | Provider type selection | `"github"`, `"gitbucket"`, `"local"` |
| `CODE_PROVIDER_BASE_URL` | Self-hosted server URL | `"https://git.company.com"` |
| `CODE_PROVIDER_TOKEN` | Primary authentication token | Personal Access Token |
| `CODE_PROVIDER_TOKEN_POOL` | Comma-separated token list | `"token1,token2,token3"` |
| `CODE_PROVIDER_USERNAME` | Basic auth username | For GitBucket/GitLab |
| `CODE_PROVIDER_PASSWORD` | Basic auth password | For GitBucket/GitLab |
| `REPO_MANAGER_ENABLED` | Enable local caching via RepoManager | `"true"` or `"false"` |

**Sources:**
- [app/core/config_provider.py:219-243]()
- [app/modules/code_provider/code_provider_service.py:162-164]()

### ICodeProvider Interface

All providers implement a standard interface that abstracts provider-specific details:

| Method | Purpose | Return Type |
|--------|---------|-------------|
| `get_repository(repo_name)` | Fetch repository metadata | `dict` with name, owner, default_branch |
| `get_file_content(repo_name, file_path, ref, start_line, end_line)` | Retrieve file content | `str` (decoded content) |
| `get_branch(repo_name, branch_name)` | Get branch information | `dict` with name, commit_sha, protected |
| `get_archive_link(repo_name, format_type, ref)` | Generate archive URL | `str` (download URL) |
| `get_repository_structure(repo_name, path, ref, max_depth)` | Fetch directory tree | Nested `dict` structure |
| `get_client()` | Get provider-specific client | Provider-specific client object |

**Sources:**
- [app/modules/code_provider/code_provider_service.py:14-141]() (MockRepo interface)
- [app/modules/code_provider/code_provider_service.py:236-238]()

---

## Authentication Fallback Chain

Potpie implements a sophisticated fallback strategy to ensure reliable repository access even when primary authentication fails.

### GitHub Provider Fallback Sequence

**Title: GitHub Authentication Fallback Chain**

```mermaid
graph TD
    Start["Repository Access Attempt"]
    
    Primary["Try Primary Method<br/>GitHub App Installation"]
    PrimarySuccess{"Success?"}
    
    Secondary["Try PAT Token Pool<br/>CODE_PROVIDER_TOKEN_POOL"]
    SecondarySuccess{"Success?"}
    
    Tertiary["Try Single PAT<br/>CODE_PROVIDER_TOKEN"]
    TertiarySuccess{"Success?"}
    
    Check401{"401 Unauthorized?"}
    
    Unauth["Fallback: Unauthenticated<br/>Public repos only"]
    UnauthSuccess{"Success?"}
    
    Success["Return Repository Data"]
    Fail["Raise HTTPException<br/>Authentication Failed"]
    
    Start --> Primary
    Primary --> PrimarySuccess
    
    PrimarySuccess -->|Yes| Success
    PrimarySuccess -->|No| Secondary
    
    Secondary --> SecondarySuccess
    SecondarySuccess -->|Yes| Success
    SecondarySuccess -->|No| Tertiary
    
    Tertiary --> TertiarySuccess
    TertiarySuccess -->|Yes| Success
    TertiarySuccess -->|No| Check401
    
    Check401 -->|Yes & GitHub| Unauth
    Check401 -->|No| Fail
    
    Unauth --> UnauthSuccess
    UnauthSuccess -->|Yes| Success
    UnauthSuccess -->|No| Fail
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:156-202]()
- [app/modules/code_provider/code_provider_service.py:218-262]()

### Fallback Logic Implementation

The `ProviderWrapper.get_repo()` method implements the fallback chain:

```python
# Primary: Use CodeProviderFactory with all authentication methods
provider = CodeProviderFactory.create_provider_with_fallback(repo_name)

try:
    repo_info = provider.get_repository(repo_name)
except Exception as e:
    # Check for 401 (Bad Credentials) errors
    is_401_error = (
        isinstance(e, BadCredentialsException)
        or "401" in str(e)
        or "Bad credentials" in str(e)
    )
    
    # Only GitHub supports unauthenticated fallback
    provider_type = os.getenv("CODE_PROVIDER", "github").lower()
    
    if provider_type == "github" and is_401_error:
        # Final fallback: Unauthenticated access for public repos
        unauth_provider = GitHubProvider()
        unauth_provider.set_unauthenticated_client()
        repo_info = unauth_provider.get_repository(repo_name)
    else:
        raise  # Propagate non-401 errors or non-GitHub failures
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:169-194]()

### Error Detection and Recovery

The system detects authentication failures through multiple signals:

| Error Signal | Detection Method | Recovery Action |
|--------------|-----------------|-----------------|
| `BadCredentialsException` | PyGithub exception type | Try next auth method |
| HTTP 401 status | Check exception status attribute | Try next auth method |
| "401" in error message | String matching | Try next auth method |
| "Bad credentials" text | String matching | Try next auth method |
| Rate limit exceeded | Check `X-RateLimit-Remaining` header | Switch to token pool |

**Sources:**
- [app/modules/code_provider/code_provider_service.py:171-176]()
- [app/modules/code_provider/code_provider_service.py:231-236]()

---

## RepoManager Integration

The `RepoManager` provides transparent local caching of repositories to reduce API calls and improve performance.

### RepoManager Architecture

**Title: RepoManager Local Caching Strategy**

```mermaid
graph TB
    Request["File/Structure Request"]
    
    Wrapper["ProviderWrapper<br/>_wrap_provider_if_needed()"]
    
    Check["Check REPO_MANAGER_ENABLED"]
    
    subgraph "RepoManager Layer"
        RM["RepoManager<br/>~/.repos management"]
        GetPath["get_repo_path(repo_name, ref)"]
        Worktrees["Git worktrees<br/>per branch/commit"]
    end
    
    subgraph "Provider Wrapping"
        RMWrapper["RepoManagerCodeProviderWrapper<br/>Transparent fallback"]
        CheckLocal["Check local copy exists"]
    end
    
    BaseProvider["Base ICodeProvider<br/>GitHubProvider/GitBucketProvider"]
    
    LocalOps["Local File Operations<br/>Direct file system access"]
    RemoteOps["Remote API Calls<br/>GitHub/GitBucket API"]
    
    Response["File content / Structure"]
    
    Request --> Wrapper
    Wrapper --> Check
    
    Check -->|Enabled| RM
    Check -->|Disabled| BaseProvider
    
    RM --> GetPath
    GetPath --> Worktrees
    Worktrees --> RMWrapper
    
    RMWrapper --> CheckLocal
    
    CheckLocal -->|Exists| LocalOps
    CheckLocal -->|Missing| RemoteOps
    
    BaseProvider --> RemoteOps
    
    LocalOps --> Response
    RemoteOps --> Response
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:159-186]()
- [app/modules/code_provider/code_provider_service.py:354-374]()

### Local Copy Detection

The `ProviderWrapper` checks for local copies before making remote API calls:

```python
# Initialize repo manager if enabled
repo_manager_enabled = os.getenv("REPO_MANAGER_ENABLED", "false").lower() == "true"
if repo_manager_enabled:
    from app.modules.repo_manager import RepoManager
    self.repo_manager = RepoManager()
```

When wrapping providers, the system checks if a local copy exists:

```python
if self.repo_manager:
    # Try to get local copy path
    local_path = self.repo_manager.get_repo_path(repo_name)
    if local_path and os.path.exists(local_path):
        # Use local copy - wrap provider with RepoManagerCodeProviderWrapper
        provider = RepoManagerCodeProviderWrapper(provider, self.repo_manager)
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:162-171]()
- [app/modules/code_provider/code_provider_service.py:354-374]()

### Benefits of RepoManager

| Benefit | Description | Performance Impact |
|---------|-------------|-------------------|
| **Reduced API Calls** | File operations use local copies when available | 10-100x faster |
| **No Rate Limits** | Local operations don't consume API quota | Unlimited access |
| **Offline Access** | Can work with cached repositories without network | Works offline |
| **Worktree Support** | Multiple branches/commits available simultaneously | Parallel processing |

**Sources:**
- [app/modules/code_provider/code_provider_service.py:173-186]()
- [app/modules/code_provider/code_provider_service.py:308-373]()

---

## Provider-Specific Implementations

### GitHub Provider

GitHub is the default provider with the most comprehensive feature set and authentication options.

**Authentication Methods (in priority order):**
1. **GitHub App Installation Token**: Highest rate limits (5000 req/hr)
2. **PAT Token Pool**: Distributed rate limits across multiple tokens
3. **Single PAT**: User-provided personal access token
4. **Unauthenticated**: Public repositories only (60 req/hr)

**API Endpoints Used:**
- `GET /repos/{owner}/{repo}` - Repository metadata
- `GET /repos/{owner}/{repo}/contents/{path}` - File content (base64 encoded)
- `GET /repos/{owner}/{repo}/tarball/{ref}` - Archive download
- `GET /repos/{owner}/{repo}/branches` - Branch listing
- `GET /repos/{owner}/{repo}/git/trees/{sha}` - Repository tree

**Sources:**
- [app/modules/code_provider/code_provider_service.py:196-198]()

### GitBucket Provider

GitBucket is a self-hosted Git platform with GitHub-compatible APIs but different archive URL formats.

**Configuration:**
```bash
CODE_PROVIDER=gitbucket
CODE_PROVIDER_BASE_URL=https://gitbucket.company.com
CODE_PROVIDER_TOKEN=your_access_token
REPO_MANAGER_ENABLED=true  # Optional: Enable local caching
```

**Key Differences from GitHub:**

| Feature | GitHub Format | GitBucket Format |
|---------|---------------|------------------|
| Archive URL | `/repos/{owner}/{repo}/tarball/{ref}` | `/{owner}/{repo}/archive/{ref}.tar.gz` |
| API Base | `https://api.github.com` | `https://host/api/v3` |
| Repository Names | Normalized to `owner/repo` | Internal format: `root/repo` |

**Archive Link Generation:**

The `MockRepo.get_archive_link()` method handles GitBucket-specific URL formatting:

```python
# GitBucket-specific archive URL construction
if provider.get_provider_name() == "gitbucket":
    # Remove /api/v3 from base URL
    base_url = base_url[:-7] if base_url.endswith("/api/v3") else base_url
    
    # Use actual repo name (root/repo) for URL
    actual_repo_name = get_actual_repo_name_for_lookup(full_name, "gitbucket")
    
    # GitBucket format: /owner/repo/archive/ref.tar.gz
    archive_url = f"{base_url}/{actual_repo_name}/archive/{ref}.tar.gz"
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:83-107]()

### Local Provider

The `LocalProvider` supports parsing repositories from the local file system without network access.

**Configuration:**
```bash
CODE_PROVIDER=local
# No authentication required
```

**Path Detection:**

The system auto-detects local paths based on these criteria:

```python
is_local_path = (
    os.path.isabs(repo_name)                              # Absolute path
    or repo_name.startswith(("~", "./", "../"))           # Relative path
    or os.path.isdir(os.path.expanduser(repo_name))       # Valid directory
)
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:293-298]()

**File Access:**

Local repositories use direct file system operations:

```python
# Read file content directly
with open(file_full_path, "r", encoding="utf-8") as file:
    lines = file.readlines()
    
# Repository structure via os.listdir()
for item in os.listdir(abs_path):
    item_path = os.path.join(abs_path, item)
    if os.path.isdir(item_path):
        # Handle directory
    elif os.path.isfile(item_path):
        # Handle file
```

**Sources:**
- [app/modules/code_provider/local_repo/local_repo_service.py:81-88]()
- [app/modules/code_provider/local_repo/local_repo_service.py:380-411]()

**Gitignore Support:**

Local repositories respect `.gitignore` patterns to exclude files:

```python
# Load .gitignore patterns
gitignore_spec = pathspec.PathSpec.from_lines(
    pathspec.patterns.GitWildMatchPattern,
    gitignore_content.splitlines()
)

# Check if file should be ignored
if gitignore_spec.match_file(relative_path):
    continue  # Skip ignored file
```

**Sources:**
- [app/modules/code_provider/local_repo/local_repo_service.py:134-158]()
- [app/modules/code_provider/local_repo/local_repo_service.py:239-247]()

---

## Provider Wrapper and Unified Interface

The `ProviderWrapper` class provides a consistent interface to downstream services regardless of the underlying provider.

### Wrapper Architecture

**Title: ProviderWrapper Integration with Downstream Services**

```mermaid
graph TB
    subgraph "API Layer"
        FileAPI["GET /projects/files"]
        StructureAPI["GET /projects/{id}/structure"]
    end
    
    subgraph "Service Layer"
        CodeProviderService["CodeProviderService<br/>_get_service_instance()"]
        ProviderWrapper["ProviderWrapper<br/>__init__(sql_db)"]
    end
    
    subgraph "Provider Selection"
        Factory["CodeProviderFactory.create_provider_with_fallback()"]
        GitHubProv["GitHubProvider"]
        GitBucketProv["GitBucketProvider"]
        LocalProv["LocalProvider"]
    end
    
    subgraph "Optional Caching Layer"
        CheckRM["Check REPO_MANAGER_ENABLED"]
        RepoManager["RepoManager"]
        RMWrapper["RepoManagerCodeProviderWrapper<br/>_wrap_provider_if_needed()"]
    end
    
    subgraph "Unified Return Types"
        MockRepo["MockRepo<br/>Standardized interface"]
        RepoInfo["Repository metadata"]
        FileContent["File content string"]
        Structure["Directory tree dict"]
    end
    
    subgraph "Downstream Consumers"
        ParsingService["ParsingService<br/>parse_directory()"]
        ToolService["ToolService<br/>fetch_file tool"]
        GetFileStructure["GetCodeFileStructureTool<br/>fetch_repo_structure()"]
    end
    
    FileAPI --> CodeProviderService
    StructureAPI --> CodeProviderService
    
    CodeProviderService --> ProviderWrapper
    
    ProviderWrapper --> Factory
    
    Factory --> GitHubProv
    Factory --> GitBucketProv
    Factory --> LocalProv
    
    GitHubProv --> CheckRM
    GitBucketProv --> CheckRM
    LocalProv --> CheckRM
    
    CheckRM -->|Enabled| RepoManager
    CheckRM -->|Disabled| MockRepo
    
    RepoManager --> RMWrapper
    RMWrapper --> MockRepo
    
    MockRepo --> RepoInfo
    MockRepo --> FileContent
    MockRepo --> Structure
    
    RepoInfo --> ParsingService
    FileContent --> ToolService
    Structure --> GetFileStructure
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:155-186]()
- [app/modules/code_provider/code_provider_service.py:431-441]()
- [app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py:23-48]()

### MockRepo Pattern

The `MockRepo` class wraps provider-specific implementations to present a GitHub-compatible interface:

```python
class MockRepo:
    def __init__(self, repo_info, provider):
        self.full_name = repo_info["full_name"]
        self.owner = type("Owner", (), {"login": repo_info["owner"]})()
        self.default_branch = repo_info["default_branch"]
        self.private = repo_info["private"]
        self._provider = provider  # Store provider reference
    
    def get_archive_link(self, format_type, ref):
        # Delegate to provider with special handling for GitBucket
        if hasattr(self._provider, "get_archive_link"):
            return self._provider.get_archive_link(self.full_name, format_type, ref)
        else:
            # Construct URL based on provider type
            if self._provider.get_provider_name() == "gitbucket":
                # GitBucket-specific URL format
                return f"{base_url}/{actual_repo_name}/archive/{ref}.tar.gz"
            else:
                # Standard GitHub format
                return f"{base_url}/repos/{self.full_name}/tarball/{ref}"
    
    def get_branch(self, branch_name):
        # Delegate to provider's get_branch method
        branch_info = self._provider.get_branch(self.full_name, branch_name)
        return MockBranch(branch_info)
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:14-141]()

### Service Integration

The `CodeProviderService` facade simplifies provider access for downstream services:

| Method | Purpose | Delegates To |
|--------|---------|-------------|
| `get_repo(repo_name)` | Get repository metadata | `ProviderWrapper.get_repo()` |
| `get_file_content(...)` | Retrieve file content with line ranges | `ProviderWrapper.get_file_content()` |
| `get_project_structure_async(project_id, path)` | Get directory tree | `ProviderWrapper.get_project_structure_async()` |

Implementation in `CodeProviderService`:

```python
class CodeProviderService:
    def __init__(self, sql_db):
        self.sql_db = sql_db
        self.service_instance = self._get_service_instance()
    
    def _get_service_instance(self):
        # Always use ProviderWrapper for unified provider access
        return ProviderWrapper(self.sql_db)
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:431-467]()

---

## Repository Structure Retrieval

The system retrieves repository directory structures with provider-specific optimizations.

### Structure Request Flow

**Title: Multi-Provider Structure Retrieval**

```mermaid
sequenceDiagram
    participant Tool as "get_code_file_structure_tool"
    participant CPS as "CodeProviderService"
    participant Wrapper as "ProviderWrapper"
    participant PM as "ProjectService"
    participant Provider as "ICodeProvider"
    participant Cache as "Redis Cache"
    
    Tool->>CPS: get_project_structure_async(project_id)
    CPS->>Wrapper: get_project_structure_async(project_id)
    
    Wrapper->>PM: get_project_from_db_by_id(project_id)
    PM-->>Wrapper: project (repo_name, repo_path)
    
    Wrapper->>Wrapper: Detect local vs remote<br/>os.path.isabs() checks
    
    alt Local Repository
        Wrapper->>Provider: LocalProvider.get_repository_structure()
        Provider->>Provider: os.listdir() + pathspec filtering
        Provider-->>Wrapper: Directory tree dict
    else GitHub Repository (cached)
        Wrapper->>Cache: Check project_structure:{project_id}
        Cache-->>Wrapper: Cached structure (TTL: 1hr)
    else GitHub Repository (uncached)
        Wrapper->>Provider: GithubService.get_project_structure_async()
        Provider->>Provider: GitHub Tree API + pagination
        Provider->>Cache: Store structure (TTL: 1hr)
        Provider-->>Wrapper: Fresh structure
    else Other Remote Repository
        Wrapper->>Provider: Provider.get_repository_structure()
        Provider-->>Wrapper: Directory tree dict
    end
    
    Wrapper-->>CPS: Formatted structure
    CPS-->>Tool: Structure string/dict
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:264-339]()
- [app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py:32-48]()

### Provider-Specific Structure Handling

| Provider | Implementation | Caching | Format |
|----------|---------------|---------|--------|
| GitHub (remote) | `GithubService.get_project_structure_async()` | Redis (1hr TTL) | Formatted string |
| GitHub (local copy) | `RepoManagerCodeProviderWrapper` + `LocalProvider` | No caching | Nested dict |
| GitBucket | `Provider.get_repository_structure()` | No caching | Nested dict |
| Local | `LocalProvider.get_repository_structure()` | No caching | Nested dict |

**Structure Retrieval Priority:**

The system checks for repository sources in this order:

1. **RepoManager local copy** (if `REPO_MANAGER_ENABLED=true`)
2. **Local file system path** (if path-like repo_name)
3. **GitHub cached structure** (if Redis cache hit)
4. **Remote API call** (fallback for all providers)

**GitHub-Specific Optimizations:**
- Async handling with proper depth tracking
- Redis caching for repeated access (1-hour TTL)
- Formatted string output for tool consumption
- Better performance for remote APIs

**Local Repository Features:**
- Direct file system traversal via `os.listdir()`
- Respects `.gitignore` patterns using `pathspec` library
- Excludes common binary extensions (images, videos, notebooks)
- Max depth limit (default: 4 levels) to prevent excessive recursion

**Sources:**
- [app/modules/code_provider/code_provider_service.py:308-422]()
- [app/modules/code_provider/local_repo/local_repo_service.py:99-158]()
- [app/modules/code_provider/local_repo/local_repo_service.py:168-186]()

---

## File Content Retrieval

File content retrieval is provider-agnostic through the `ICodeProvider` interface.

### Content Request Flow

**Title: Provider-Agnostic File Content Retrieval**

```mermaid
graph TB
    Request["File Content Request<br/>repo_name, file_path, ref"]
    
    Service["CodeProviderService.get_file_content()"]
    
    Wrapper["ProviderWrapper.get_file_content()"]
    
    Factory["CodeProviderFactory.create_provider_with_fallback()"]
    
    subgraph "Provider Implementations"
        GitHub["GitHubProvider<br/>GET /repos/{owner}/{repo}/contents/{path}"]
        GitBucket["GitBucketProvider<br/>GET /api/v3/repos/{owner}/{repo}/contents"]
        Local["LocalProvider<br/>open(file_path, 'r')"]
    end
    
    subgraph "Content Processing"
        Decode["Base64 Decode<br/>(Remote providers)"]
        Encoding["Encoding Detection<br/>chardet library"]
        Lines["Line Selection<br/>start_line to end_line"]
    end
    
    Fallback401{"401 Error?"}
    Unauth["Fallback to Unauthenticated<br/>(GitHub only)"]
    
    Response["Return file content string"]
    
    Request --> Service
    Service --> Wrapper
    Wrapper --> Factory
    
    Factory --> GitHub
    Factory --> GitBucket
    Factory --> Local
    
    GitHub --> Fallback401
    GitBucket --> Decode
    Local --> Lines
    
    Fallback401 -->|Yes| Unauth
    Fallback401 -->|No| Decode
    
    Unauth --> Decode
    Decode --> Encoding
    Encoding --> Lines
    Lines --> Response
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:203-262]()
- [app/modules/code_provider/code_provider_service.py:359-377]()

### Line Range Selection

File content retrieval supports extracting specific line ranges:

```python
# Line range parameters
start_line: int  # Starting line number (1-indexed)
end_line: int    # Ending line number (inclusive)

# Special cases
if start_line == 0 and end_line == 0:
    return entire_file
    
# Context padding (local provider)
start = start_line - 2 if start_line - 2 > 0 else 0
selected_lines = lines[start:end_line]
```

**Sources:**
- [app/modules/code_provider/local_repo/local_repo_service.py:84-88]()

### Provider-Specific Content Handling

| Provider | API Format | Encoding | Line Selection |
|----------|-----------|----------|---------------|
| GitHub | Base64 in JSON response | UTF-8 after decode | Server-side |
| GitBucket | Base64 in JSON response | UTF-8 after decode | Server-side |
| Local | Raw file bytes | Detected with chardet | Client-side |

**Sources:**
- [app/modules/code_provider/code_provider_service.py:222-228]()

---

## Configuration and Deployment

### Environment Variable Reference

Complete configuration options for multi-provider support:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `CODE_PROVIDER` | No | `"github"` | Provider type: `github`, `gitbucket`, `gitlab`, `local` |
| `CODE_PROVIDER_BASE_URL` | Conditional | None | Self-hosted server URL (required for non-GitHub) |
| `CODE_PROVIDER_TOKEN` | No | None | Primary authentication token (PAT) |
| `CODE_PROVIDER_TOKEN_POOL` | No | `""` | Comma-separated token list for distribution |
| `CODE_PROVIDER_USERNAME` | No | None | Basic auth username (GitBucket/GitLab) |
| `CODE_PROVIDER_PASSWORD` | No | None | Basic auth password (GitBucket/GitLab) |
| `GITHUB_PRIVATE_KEY` | No | None | GitHub App private key (highest priority) |
| `GITHUB_APP_ID` | No | None | GitHub App ID (required with private key) |

**Sources:**
- [app/core/config_provider.py:197-221]()

### Provider Configuration Examples

**GitHub with App Authentication + RepoManager:**
```bash
CODE_PROVIDER=github
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
CODE_PROVIDER_TOKEN_POOL=token1,token2,token3  # Optional fallback
REPO_MANAGER_ENABLED=true  # Enable local caching
```

**GitBucket Self-Hosted:**
```bash
CODE_PROVIDER=gitbucket
CODE_PROVIDER_BASE_URL=https://git.company.com
CODE_PROVIDER_TOKEN=your_personal_access_token
REPO_MANAGER_ENABLED=true  # Optional: Enable local caching
```

**Local Repository:**
```bash
CODE_PROVIDER=local
# No authentication needed
# Repositories specified by absolute or relative paths
```

**GitHub with PAT Pool Only:**
```bash
CODE_PROVIDER=github
CODE_PROVIDER_TOKEN_POOL=ghp_token1,ghp_token2,ghp_token3
REPO_MANAGER_ENABLED=false  # Disable local caching
```

### Validation and Health Checks

The system validates provider configuration on startup:

```python
def is_github_configured() -> bool:
    """Check if GitHub credentials are configured."""
    return bool(self.github_key and os.getenv("GITHUB_APP_ID"))
```

The `ProviderWrapper` logs warnings if `RepoManager` initialization fails:

```python
repo_manager_enabled = os.getenv("REPO_MANAGER_ENABLED", "false").lower() == "true"
if repo_manager_enabled:
    try:
        from app.modules.repo_manager import RepoManager
        self.repo_manager = RepoManager()
        logger.info("ProviderWrapper: RepoManager initialized")
    except Exception as e:
        logger.warning(f"ProviderWrapper: Failed to initialize RepoManager: {e}")
```

**Sources:**
- [app/core/config_provider.py:78-80]()
- [app/modules/code_provider/code_provider_service.py:162-171]()

### Provider Selection Logic

The factory automatically selects the appropriate provider:

1. **Check `CODE_PROVIDER` environment variable** (explicit selection)
2. **Detect local path** via `os.path.isabs()`, `repo_name.startswith(("~", "./", "../"))`, and `os.path.isdir()` checks
3. **Default to GitHub** if no explicit configuration

The `get_project_structure_async()` method implements path detection:

```python
# Auto-detect local paths
is_local_path = (
    os.path.isabs(repo_name)
    or repo_name.startswith(("~", "./", "../"))
    or os.path.isdir(os.path.expanduser(repo_name))
)

# Determine provider type
provider_type = os.getenv("CODE_PROVIDER", "github").lower()
```

**Sources:**
- [app/modules/code_provider/code_provider_service.py:345-353]()

---

## Related Systems

Repository access patterns interact with these subsystems:

- **[GitHub Service](#6.1)**: Provides authentication and API client
- **[Project Service](#6.2)**: Manages project lifecycle and status
- **[Parsing System](#4.1)**: Consumes repository data for graph construction
- **[Redis Architecture](#10.3)**: Provides caching layer
- **[Tool System](#5)**: Uses file access for code analysis tools