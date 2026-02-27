4.1-Repository Parsing Pipeline

# Page: Repository Parsing Pipeline

# Repository Parsing Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/core/config_provider.py](app/core/config_provider.py)
- [app/modules/code_provider/code_provider_service.py](app/modules/code_provider/code_provider_service.py)
- [app/modules/code_provider/local_repo/local_repo_service.py](app/modules/code_provider/local_repo/local_repo_service.py)
- [app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py](app/modules/intelligence/tools/code_query_tools/get_code_file_structure.py)
- [app/modules/parsing/graph_construction/code_graph_service.py](app/modules/parsing/graph_construction/code_graph_service.py)
- [app/modules/parsing/graph_construction/parsing_controller.py](app/modules/parsing/graph_construction/parsing_controller.py)
- [app/modules/parsing/graph_construction/parsing_helper.py](app/modules/parsing/graph_construction/parsing_helper.py)
- [app/modules/parsing/graph_construction/parsing_service.py](app/modules/parsing/graph_construction/parsing_service.py)
- [app/modules/parsing/knowledge_graph/inference_service.py](app/modules/parsing/knowledge_graph/inference_service.py)
- [app/modules/projects/projects_service.py](app/modules/projects/projects_service.py)

</details>



## Purpose and Scope

The repository parsing pipeline transforms source code repositories into queryable Neo4j knowledge graphs with AI-generated docstrings and embeddings. Entry point is `ParsingController.parse_directory()` at `POST /api/v1/parse`, which dispatches `process_parsing.delay()` Celery tasks that orchestrate `ParsingService`, `CodeGraphService`, and `InferenceService`.

The pipeline supports multiple code providers (GitHub, GitBucket, local filesystem) via `CodeProviderService`, uses tree-sitter parsers for AST extraction via `RepoMap`, and enriches graphs with LLM-generated docstrings via `ProviderService` and SentenceTransformer embeddings.

For Neo4j schema details, see [Neo4j Graph Structure](#4.3). For AI docstring generation and caching, see [Inference and Docstring Generation](#4.2). For multi-provider configuration, see [Code Provider System](#4.4).

---

## Pipeline Overview

The pipeline operates in three high-level phases (Ingestion → Graph Construction → Enrichment), implemented as six sequential stages executed asynchronously via Celery:

**Three-Phase Model (High-Level)**:
1. **Ingestion Phase**: Repository validation, acquisition, and language detection
2. **Graph Construction Phase**: Tree-sitter parsing and Neo4j bulk insertion
3. **Enrichment Phase**: LLM docstring generation, embedding creation, and indexing

**Six-Stage Implementation (Detailed)**:
</old_str>

<old_str>
**ParsingController Request Routing**

```mermaid
graph TB
    A["POST /api/v1/parse<br/>ParsingRequest"]
    B["ParsingController<br/>parse_directory()"]
    C["@validate_parsing_input<br/>schema validation"]
    D["Auto-detect filesystem path<br/>is_path = os.path.isabs()<br/>lines 56-68"]
    E{"config_provider<br/>get_is_development_mode()"}
    F["Prioritize repo_path<br/>set repo_name = None<br/>lines 70-74"]
    G["normalize_repo_name()<br/>remove .git, lowercase<br/>line 114"]
    H["ProjectService<br/>get_project_from_db()"]
    I{"Project exists?"}
    J["ParseHelper<br/>check_commit_status()"]
    K{"commit matches<br/>and status==READY?"}
    L["process_parsing.delay()<br/>Celery task"]
    M["Return existing project<br/>status: READY"]
    N["handle_new_project()<br/>register_project()<br/>lines 258-304"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E -->|enabled| F
    E -->|disabled| G
    F --> G
    G --> H
    H --> I
    I -->|Yes| J
    I -->|No| N
    J --> K
    K -->|No| L
    K -->|Yes| M
    N --> L
```
</old_str>

<new_str>
**Mapping High-Level Phases to Implementation Stages**:

| High-Level Phase | Implementation Stages | Key Components |
|------------------|----------------------|----------------|
| **Ingestion** | 1. Request Ingestion<br/>2. Repository Acquisition<br/>3. Code Structure Analysis | `ParsingController`, `ParseHelper`, `CodeProviderService` |
| **Graph Construction** | 4. Graph Construction<br/>5. Neo4j Persistence | `RepoMap`, `CodeGraphService`, `SearchService` |
| **Enrichment** | 6. AI Enhancement | `InferenceService`, `ProviderService`, `SentenceTransformer` |

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:39-304](), [app/modules/parsing/graph_construction/parsing_service.py:102-273](), [app/modules/parsing/graph_construction/parsing_helper.py:34-866](), [app/modules/parsing/graph_construction/code_graph_service.py:37-179](), [app/modules/parsing/graph_construction/parsing_repomap.py:611-736](), [app/modules/parsing/knowledge_graph/inference_service.py:741-875]()
</old_str>

<old_str>
**Demo Repository Fast-Path Duplication**

```mermaid
graph TB
    A["User requests<br/>langchain-ai/langchain"]
    B["ParsingController<br/>repo in demo_repos list?"]
    C["ProjectService<br/>get_global_project_from_db()"]
    D["Found existing:<br/>old_project_id"]
    E["uuid7() generates<br/>new_project_id"]
    F["ProjectService<br/>duplicate_project()"]
    G["ParsingService<br/>duplicate_graph()"]
    H["Neo4j UNWIND batch<br/>MATCH old nodes<br/>CREATE new nodes<br/>batch_size=3000"]
    I["Neo4j UNWIND batch<br/>MATCH old relationships<br/>CREATE new relationships<br/>batch_size=3000"]
    J["SearchService<br/>clone_search_indices()"]
    K["update_project_status()<br/>READY"]
    L["CodeProviderService<br/>get_project_structure_async()<br/>background task"]
    M["EmailHelper<br/>send_email()"]
    
    A --> B
    B -->|Yes| C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L
    K --> M
```
</old_str>

<new_str>
### API Entry Point and Request Validation

The pipeline begins at `POST /api/v1/parse` handled by `ParsingController.parse_directory()` [parsing_controller.py:42-255](). The method applies `@validate_parsing_input` decorator [parsing_controller.py:41]() for schema validation, then processes the `ParsingRequest` containing `repo_name`, `branch_name`, `commit_id`, and optional `repo_path`.

**Pipeline Flow Diagram: From API Request to Queryable Knowledge Graph**

```mermaid
graph TB
    subgraph "Phase_1[Phase 1: Request Ingestion]"
        A1["POST /api/v1/parse<br/>ParsingRequest"]
        A2["ParsingController<br/>parse_directory()"]
        A3{"demo_repos list?"}
        A4["ProjectService<br/>get_global_project_from_db()"]
        A5["ProjectService<br/>register_project()"]
    end
    
    subgraph "Phase_2[Phase 2: Repository Acquisition]"
        B1["process_parsing.delay()<br/>Celery task"]
        B2["ParseHelper<br/>clone_or_copy_repository()"]
        B3{"repo_path<br/>exists?"}
        B4["Repo(repo_path)<br/>Local filesystem"]
        B5["CodeProviderService<br/>get_repo()"]
        B6["download_and_extract_tarball()<br/>or _clone_repository_with_auth()"]
    end
    
    subgraph "Phase_3[Phase 3: Code Analysis]"
        C1["ParseHelper<br/>detect_repo_language()"]
        C2["Walk files, count extensions:<br/>.py, .js, .java, .ts, etc."]
        C3["Return predominant language<br/>or 'other' if unsupported"]
    end
    
    subgraph "Phase_4[Phase 4: Graph Construction]"
        D1["RepoMap<br/>create_graph()"]
        D2["get_tags() per file<br/>tree-sitter Query"]
        D3["Extract name.definition.*<br/>class, function, method, interface"]
        D4["Extract name.reference.*<br/>calls, imports"]
        D5["Build nx.MultiDiGraph<br/>nodes + edges"]
        D6["Create CONTAINS<br/>and REFERENCES edges"]
    end
    
    subgraph "Phase_5[Phase 5: Neo4j Persistence]"
        E1["CodeGraphService<br/>create_and_store_graph()"]
        E2["Batch create NODE nodes<br/>batch_size=1000"]
        E3["Batch create relationships<br/>by type, batch_size=1000"]
        E4["Create Neo4j indices<br/>node_id_repo_idx, etc."]
        E5["SearchService<br/>bulk_create_search_indices()"]
    end
    
    subgraph "Phase_6[Phase 6: AI Enhancement]"
        F1["InferenceService<br/>run_inference()"]
        F2["fetch_graph() from Neo4j"]
        F3["batch_nodes()<br/>with InferenceCacheService"]
        F4["generate_docstrings()<br/>ProviderService LLM calls"]
        F5["SentenceTransformer<br/>all-MiniLM-L6-v2"]
        F6["Update Neo4j SET<br/>n.docstring, n.embedding"]
    end
    
    A1 --> A2
    A2 --> A3
    A3 -->|"Yes"| A4
    A3 -->|"No"| A5
    A4 --> A5
    A5 --> B1
    
    B1 --> B2
    B2 --> B3
    B3 -->|"Yes"| B4
    B3 -->|"No"| B5
    B5 --> B6
    B4 --> C1
    B6 --> C1
    
    C1 --> C2
    C2 --> C3
    C3 --> D1
    
    D1 --> D2
    D2 --> D3
    D3 --> D4
    D4 --> D5
    D5 --> D6
    D6 --> E1
    
    E1 --> E2
    E2 --> E3
    E3 --> E4
    E4 --> E5
    E5 --> F1
    
    F1 --> F2
    F2 --> F3
    F3 --> F4
    F4 --> F5
    F5 --> F6
```

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:39-304](), [app/modules/parsing/graph_construction/parsing_service.py:102-273](), [app/modules/parsing/graph_construction/parsing_helper.py:34-866](), [app/modules/parsing/graph_construction/code_graph_service.py:37-179](), [app/modules/parsing/graph_construction/parsing_repomap.py:611-736](), [app/modules/parsing/knowledge_graph/inference_service.py:741-875]()

---

## Phase 1: Request Ingestion

### API Entry Point

The parsing pipeline begins at the `POST /api/v1/parse` endpoint handled by `ParsingController.parse_directory()`. This method validates the request, normalizes repository names, and determines whether to create a new project or update an existing one.

### Celery Background Task Dispatch

After validation, `process_parsing.delay()` enqueues a Celery task [parsing_controller.py:216-222](), [parsing_controller.py:287-293]():

**Task Invocation**:
```python
process_parsing.delay(
    repo_details.model_dump(),  # ParsingRequest serialized to dict
    user_id,                     # str: user identifier
    user_email,                  # str: for EmailHelper notification
    project_id,                  # str: UUID7 project identifier
    cleanup_graph                # bool: delete existing Neo4j nodes
)
```

The Celery worker calls `ParsingService.parse_directory()` [parsing_service.py:102-262]() with `log_context(project_id=str(project_id), user_id=user_id)` [parsing_service.py:111]() for structured logging.

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:216-222](), [app/modules/parsing/graph_construction/parsing_controller.py:287-293](), [app/celery/tasks/parsing_tasks.py](), [app/modules/parsing/graph_construction/parsing_service.py:102-113]()

**Key Validation Logic:**

- **Path Auto-Detection** [parsing_controller.py:56-68](): If `repo_name` looks like a filesystem path (absolute, starts with `~`, `./`, `../`, or exists as directory), it's automatically moved to `repo_path`
- **Development Mode Constraints** [parsing_controller.py:86-90](): Local repository parsing (`repo_path`) only allowed when `isDevelopmentMode=enabled`
- **Repository Normalization** [parsing_controller.py:114](): Repository names are normalized using `normalize_repo_name()` for consistent database lookups (removes `.git` suffix, lowercases)

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:42-255]()

---

### Demo Repository Fast-Path

For a predefined list of demo repositories, the system supports instant duplication from an existing parsed graph:

**Demo Repository List** [parsing_controller.py:102-110]():
- `Portkey-AI/gateway`
- `crewAIInc/crewAI`
- `AgentOps-AI/agentops`
- `calcom/cal.com`
- `langchain-ai/langchain`
- `AgentOps-AI/AgentStack`
- `formbricks/formbricks`

**Fast-Path Flow** [parsing_controller.py:128-177]():

1. Check if demo repository has been parsed before by any user via `get_global_project_from_db()`
2. If global project exists: `duplicate_project()` + `duplicate_graph()`
3. Copy all nodes and relationships under new `repoId` in Neo4j using `UNWIND` batches
4. Update project status to `READY` immediately
5. Asynchronously fetch project structure via `CodeProviderService.get_project_structure_async()`

This optimization allows new users to access demo repositories within seconds instead of waiting 5-10 minutes for full parsing.

**Demo Repository Duplication Flow**

```mermaid
graph LR
    A["User alice requests<br/>langchain-ai/langchain"]
    B["ProjectService<br/>get_global_project_from_db()"]
    C["Found existing graph<br/>repoId: old_proj_id"]
    D["ProjectService<br/>duplicate_project()<br/>new_project_id: new_proj_id"]
    E["ParsingService<br/>duplicate_graph()"]
    F["Neo4j MATCH nodes<br/>batch_size=3000<br/>lines 395-433"]
    G["Neo4j MATCH relationships<br/>batch_size=3000<br/>lines 438-465"]
    H["SearchService<br/>clone_search_indices()"]
    I["Status = READY<br/>EmailHelper notification"]
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
```

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:128-177](), [app/modules/parsing/graph_construction/parsing_service.py:387-477](), [app/modules/projects/projects_service.py:154-175]()

---

## Phase 2: Repository Acquisition

### Celery Task Dispatch

Once validation passes, a `process_parsing` Celery task is queued for background execution:

**Task Signature** [parsing_controller.py:216-222]():
```python
process_parsing.delay(
    repo_details.model_dump(),  # ParsingRequest as dict
    user_id,                     # String user ID
    user_email,                  # For completion notification
    project_id,                  # UUID7 project identifier
    cleanup_graph                # Boolean: delete existing graph first
)
```

The task invokes `ParsingService.parse_directory()` which orchestrates the remaining phases with logging context bound to `project_id` and `user_id` [parsing_service.py:111]().

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:216-222](), [app/celery/tasks/parsing_tasks.py](), [app/modules/parsing/graph_construction/parsing_service.py:102-113]()

---

### Repository Source Resolution

`ParseHelper.clone_or_copy_repository()` determines the repository source and authentication method:

| Source Type | Detection | Action | Auth Method |
|-------------|-----------|--------|-------------|
| **Local Filesystem** | `repo_details.repo_path` exists [line 70]() | Create `Repo()` object from path [line 76]() | None required |
| **GitHub** | `repo_details.repo_name` provided | `CodeProviderService.get_repo()` [line 82]() | GitHub App JWT or PAT |
| **GitBucket** | `CODE_PROVIDER=gitbucket` | `CodeProviderService.get_repo()` | Token or Basic Auth |
| **GitLab** | `CODE_PROVIDER=gitlab` | `CodeProviderService.get_repo()` | OAuth token |

The method returns a tuple `(repo, owner, auth)` where `repo` is either a `git.Repo` object (local) or a PyGithub `Repository` object (remote), `owner` is the repository owner login, and `auth` is the authentication object extracted from the GitHub client.

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:63-107]()

---

### Tarball Download Strategy

For remote repositories, the system prefers tarball download over git clone for performance:

**RepoMap Graph Construction with tree-sitter**

```mermaid
graph TB
    subgraph Input["Repository Input"]
        A["os.walk(repo_dir)"]
        B["ParseHelper<br/>is_text_file()"]
        C["SimpleIO<br/>read_text()"]
    end
    
    subgraph TreeSitter["tree-sitter AST Parsing"]
        D["filename_to_lang()<br/>map .py → python"]
        E["get_parser(lang)<br/>Parser instance"]
        F["Load query file<br/>tree-sitter-{lang}-tags.scm"]
        G["parser.parse()<br/>bytes(code, utf-8)"]
        H["query.matches()<br/>tree.root_node"]
    end
    
    subgraph TagExtraction["Tag Classification"]
        I["name.definition.class<br/>kind='def'"]
        J["name.definition.function<br/>kind='def'"]
        K["name.definition.method<br/>kind='def'"]
        L["name.definition.interface<br/>kind='def'"]
        M["name.reference.call<br/>kind='ref'"]
    end
    
    subgraph GraphBuilding["NetworkX MultiDiGraph"]
        N["G.add_node()<br/>type=FILE"]
        O["G.add_node()<br/>type=CLASS"]
        P["G.add_node()<br/>type=FUNCTION"]
        Q["G.add_edge()<br/>FILE-[CONTAINS]->CLASS"]
        R["G.add_edge()<br/>FILE-[CONTAINS]->FUNCTION"]
        S["G.add_edge()<br/>CLASS-[CONTAINS]->METHOD"]
        T["G.add_edge()<br/>FUNCTION-[REFERENCES]->FUNCTION"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    H --> J
    H --> K
    H --> L
    H --> M
    
    I --> O
    J --> P
    K --> P
    L --> O
    M --> T
    
    N --> Q
    O --> S
    P --> R
```

**Text File Detection** [parsing_helper.py:109-201]():

The `is_text_file()` method uses a two-stage approach:
1. Check file extension against whitelist (`.py`, `.js`, `.java`, `.ts`, `.go`, `.rs`, `.rb`, etc.) [lines 155-195]() or blacklist (`.png`, `.jpg`, `.ipynb`, etc.) [lines 138-154]()
2. Attempt to read file with multiple encodings: `utf-8`, `utf-8-sig`, `utf-16`, `latin-1` [lines 120-135]()

This prevents binary files from corrupting the code graph.

**GitBucket Fallback** [parsing_helper.py:357-366]():

If tarball download returns 401 (Unauthorized) for GitBucket private repositories, the system falls back to `_clone_repository_with_auth()` which uses git clone with embedded credentials in the URL format `http://username:password@hostname/path/repo.git` [lines 542-551]().

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:203-643]()

---

### Project Directory Setup

`ParseHelper.setup_project_directory()` resolves the repository location and updates project metadata:

**Local Repository Path** [parsing_helper.py:767-816]():
- Returns `repo.working_tree_dir` directly without downloading [line 815]()
- Useful for development mode and on-premise deployments

**Remote Repository Path** [parsing_helper.py:817-866]():
- Downloads tarball to `$PROJECT_PATH/{owner-repo}-{branch}-{user_id}/`
- Checks out specific commit if `commit_id` provided using `repo_details.git.checkout(commit_id)` [line 823]()
- Updates project status to `CLONED` via `ProjectService.update_project_status()` [lines 861-863]()

The method also handles normalized repository names [lines 795-799]() and registers new projects in the database if they don't exist [lines 801-812]().

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:749-866]()

---

## Phase 3: Code Structure Analysis

### Language Detection

`ParseHelper.detect_repo_language()` analyzes file extensions to determine the predominant programming language:

**Supported Languages** [parsing_helper.py:647-747]():

| Language | Extensions | tree-sitter Parser | Count Variable |
|----------|------------|--------------------|--------------------|
| Python | `.py` | `python` | `lang_count["python"]` |
| JavaScript | `.js`, `.jsx` | `javascript` | `lang_count["javascript"]` |
| TypeScript | `.ts`, `.tsx` | `typescript` | `lang_count["typescript"]` |
| Java | `.java` | `java` | `lang_count["java"]` |
| C# | `.cs` | `c_sharp` | `lang_count["c_sharp"]` |
| Go | `.go` | `go` | `lang_count["go"]` |
| Rust | `.rs` | `rust` | `lang_count["rust"]` |
| Ruby | `.rb` | `ruby` | `lang_count["ruby"]` |
| PHP | `.php` | `php` | `lang_count["php"]` |
| C/C++ | `.c`, `.cpp`, `.cxx`, `.cc` | `c`, `cpp` | `lang_count["c"]`, `lang_count["cpp"]` |
| Markdown | `.md`, `.mdx` | - | `lang_count["markdown"]` |
| XML | `.xml`, `.xsq` | `xml` | `lang_count["xml"]` |

**Detection Algorithm** [parsing_helper.py:670-746]():
1. Walk repository directory tree using `os.walk(repo_dir)` [line 671]()
2. Skip hidden directories (`.git`, `.vscode`, etc.) [lines 672-673]()
3. Try reading each file with multiple encodings (`utf-8`, `utf-8-sig`, `utf-16`, `latin-1`) [lines 680-691]()
4. Count files by extension into `lang_count` dictionary [lines 696-731]()
5. Return language with highest count: `max(lang_count, key=lang_count.get)` [line 746]()
6. Return `"other"` if no supported language found (triggers parsing error)

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:645-747]()

---

## Phase 4: Graph Construction

### RepoMap Overview

`RepoMap.create_graph()` builds a NetworkX `MultiDiGraph` representing the codebase structure using tree-sitter parsers.

**Batch Node Creation** [code_graph_service.py:62-109]():
```python
batch_size = 1000  # Fixed batch size for performance

for i in range(0, node_count, batch_size):
    batch_nodes = list(nx_graph.nodes(data=True))[i : i + batch_size]
    nodes_to_create = []
    
    for node_id, node_data in batch_nodes:
        node_type = node_data.get("type", "UNKNOWN")
        labels = ["NODE"]  # Base label for all nodes
        
        # Add specific type label for queryability
        if node_type in ["FILE", "CLASS", "FUNCTION", "INTERFACE"]:
            labels.append(node_type)
        
        processed_node = {
            "name": node_data.get("name", node_id),
            "file_path": node_data.get("file", ""),
            "start_line": node_data.get("line", -1),
            "end_line": node_data.get("end_line", -1),
            "repoId": project_id,  # Multi-tenant partition key
            "node_id": CodeGraphService.generate_node_id(node_id, user_id),
            "entityId": user_id,
            "type": node_type,
            "text": node_data.get("text", ""),
            "labels": labels
        }
        nodes_to_create.append(processed_node)
    
    # Bulk insert with dynamic labels via APOC
    session.run("""
        UNWIND $nodes AS node
        CALL apoc.create.node(node.labels, node) YIELD node AS n
        RETURN count(*) AS created_count
    """, nodes=nodes_to_create)
```

**Sources:** [app/modules/parsing/graph_construction/parsing_repomap.py:611-736](), [app/modules/parsing/graph_construction/parsing_repomap.py:134-241]()

---

### Node Creation

**Node Types and Properties**:

| Node Type | Identifier Format | Properties | Lines |
|-----------|-------------------|------------|-------|
| **FILE** | `{rel_path}` | `file`, `type="FILE"`, `text`, `line=0`, `end_line=0`, `name` | 632-641 |
| **CLASS** | `{rel_path}:{ClassName}` | `file`, `type="CLASS"`, `name`, `line`, `end_line`, `class_name` | 670-679 |
| **INTERFACE** | `{rel_path}:{InterfaceName}` | `file`, `type="INTERFACE"`, `name`, `line`, `end_line`, `class_name` | 670-679 |
| **FUNCTION** | `{rel_path}:{ClassName}.{methodName}` or `{rel_path}:{functionName}` | `file`, `type="FUNCTION"`, `name`, `line`, `end_line`, `class_name` | 670-679 |

**Example Node Names**:
- FILE: `src/services/user.py`
- CLASS: `src/services/user.py:UserService`
- METHOD: `src/services/user.py:UserService.create_user`
- FUNCTION: `src/utils/validation.py:validate_email`

**Node Creation Logic** [parsing_repomap.py:647-693]():

1. For each tag with `kind='def'` [line 648]():
   - If `type='class'`: Create CLASS node [line 649-651](), set `current_class = tag.name`
   - If `type='interface'`: Create INTERFACE node [line 653-655](), set `current_class = tag.name`
   - If `type in ['method', 'function']`: Create FUNCTION node [line 657-659](), set `current_method = tag.name`
2. Build fully-qualified node name using context [lines 664-667]():
   - If inside class: `f"{rel_path}:{current_class}.{tag.name}"`
   - Otherwise: `f"{rel_path}:{tag.name}"`
3. Add node to graph if not already present using `G.add_node()` [line 670]()
4. Record definition in `defines[tag.name]` dictionary [line 693]()

**Sources:** [app/modules/parsing/graph_construction/parsing_repomap.py:647-693]()

---

### Relationship Creation

**Relationship Types**:

| Type | Source | Target | Meaning | Properties |
|------|--------|--------|---------|------------|
| **CONTAINS** | FILE | CLASS/FUNCTION | File contains definition | `ident`, `type` |
| **CONTAINS** | CLASS | METHOD | Class contains method | `ident`, `type` |
| **REFERENCES** | FUNCTION | FUNCTION | Function calls function | `ident`, `ref_line`, `end_ref_line` |
| **REFERENCES** | FUNCTION | CLASS | Function uses class | `ident`, `ref_line`, `end_ref_line` |

**Reference Resolution** [parsing_repomap.py:714-734]():

1. For each reference tag with `kind='ref'`:
   - Determine `source` node (current function/method context)
   - Record reference location: `(source, line, end_line, class, method)`
2. After all files processed:
   - For each identifier with references: `references[ident]`
   - Find all definitions: `defines[ident]`
   - Create REFERENCES edge from each source to each target
3. Skip self-references (`source == target`)

**Relationship Direction Validation** [parsing_repomap.py:563-609]():

The `create_relationship()` helper ensures correct directional edges:
- Interface implementations → Interface declarations
- Method callers → Method definitions
- Class usage sites → Class definitions

**Sources:** [app/modules/parsing/graph_construction/parsing_repomap.py:714-736]()

---

### tree-sitter Query Files

Tag extraction uses language-specific query files located at `app/modules/parsing/graph_construction/queries/`:

**Query File Format** [parsing_repomap.py:152-156]():
```
tree-sitter-{language}-tags.scm
```

**Example Languages**:
- `tree-sitter-python-tags.scm`
- `tree-sitter-typescript-tags.scm`
- `tree-sitter-java-tags.scm`

These `.scm` files define patterns for extracting:
- `name.definition.class`
- `name.definition.function`
- `name.definition.method`
- `name.definition.interface`
- `name.reference.call`
- `name.reference.type`

**Sources:** [app/modules/parsing/graph_construction/parsing_repomap.py:144-218]()

---

## Phase 5: Neo4j Persistence

### Batch Node Insertion

`CodeGraphService.create_and_store_graph()` transfers the NetworkX graph to Neo4j using batch operations for performance.

**Batch Insertion Strategy** [code_graph_service.py:62-109]():

**InferenceService AI Enhancement Pipeline**

```mermaid
graph TB
    subgraph Fetch["1. Node Fetching"]
        A["InferenceService<br/>run_inference()"]
        B["fetch_graph()<br/>MATCH (n:NODE {repoId})"]
        C["List[Dict]<br/>node_id, text, file_path"]
    end
    
    subgraph Batch["2. Batch Preparation with Caching"]
        D["batch_nodes()<br/>max_tokens=16000"]
        E["generate_content_hash()<br/>md5(text + type)"]
        F["InferenceCacheService<br/>get_cached_inference()"]
        G{"Cache hit?"}
        H["Store in node<br/>skip LLM batch"]
        I["Add DocstringRequest<br/>to LLM batch"]
    end
    
    subgraph LLM["3. Parallel LLM Processing"]
        J["asyncio.Semaphore()<br/>PARALLEL_REQUESTS=50"]
        K["generate_response()<br/>per batch"]
        L["ProviderService<br/>call_llm_with_structured_output()"]
        M["DocstringResponse<br/>List[DocstringNode]"]
    end
    
    subgraph Embed["4. Embedding Generation"]
        N["SentenceTransformer<br/>all-MiniLM-L6-v2"]
        O["embedding_model.encode()<br/>384-dim vector"]
    end
    
    subgraph Update["5. Neo4j Update & Cache"]
        P["MATCH (n:NODE {node_id})<br/>SET n.docstring, n.embedding"]
        Q["InferenceCacheService<br/>store_cached_inference()"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G -->|Yes| H
    G -->|No| I
    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P
    P --> Q
```

**Node ID Generation** [code_graph_service.py:20-32]():

Each node gets a deterministic MD5 hash:
```python
@staticmethod
def generate_node_id(path: str, user_id: str):
    combined_string = f"{user_id}:{path}"
    hash_object = hashlib.md5()
    hash_object.update(combined_string.encode("utf-8"))
    return hash_object.hexdigest()
```

This ensures consistent IDs across re-parses and enables cache lookups in the inference phase [#4.2]().

**Sources:** [app/modules/parsing/graph_construction/code_graph_service.py:37-109]()

---

### Batch Relationship Insertion

**Relationship Insertion by Type** [code_graph_service.py:111-159]():

1. Pre-calculate all unique relationship types from NetworkX graph
2. Filter edges by relationship type
3. For each type, batch insert in groups of 1000:

```cypher
UNWIND $edges AS edge
MATCH (source:NODE {node_id: edge.source_id, repoId: edge.repoId})
MATCH (target:NODE {node_id: edge.target_id, repoId: edge.repoId})
CREATE (source)-[r:CONTAINS {repoId: edge.repoId}]->(target)
```

**Why Type-Specific Queries?**

Cypher doesn't support parameterized relationship types in dynamic queries. Processing by type allows using concrete relationship names (`CONTAINS`, `REFERENCES`) in the query, which is more performant than dynamic relationship creation via APOC.

**Sources:** [app/modules/parsing/graph_construction/code_graph_service.py:111-159]()

---

### Index Creation

**Neo4j Indices** [code_graph_service.py:53-59]():

| Index Name | Node Label | Properties | Purpose | Line |
|------------|------------|------------|---------|------|
| `node_id_repo_idx` | NODE | `(node_id, repoId)` | Fast node lookup by ID within project | 54-58 |

**Additional Indices** (referenced but not shown in provided code):
- `node_name_repo_id_NODE` on `NODE(name, repoId)` for fast node name searches
- `relationship_type_lookup` for efficient relationship type filtering

These indices are critical for query performance, especially for:
- Agent tools querying nodes by name (e.g., `get_code_from_node_id`)
- Cross-file reference lookups (e.g., `MATCH (n)-[:REFERENCES]->(m)`)
- Neighbor traversal queries (e.g., `get_code_graph_from_node_id`)

The index creation happens before node insertion to ensure all newly created nodes are indexed immediately.

**Sources:** [app/modules/parsing/graph_construction/code_graph_service.py:53-59]()

---

### Search Index Creation

After Neo4j persistence, `SearchService.bulk_create_search_indices()` creates search indices for natural language queries:

**Bulk Index Creation** [inference_service.py:756-777]():

```python
nodes_to_index = [
    {
        "project_id": repo_id,
        "node_id": node["node_id"],
        "name": node.get("name", ""),
        "file_path": node.get("file_path", ""),
        "content": f"{node.get('name', '')} {node.get('file_path', '')}"
    }
    for node in nodes
    if node.get("file_path") not in {None, ""}
    and node.get("name") not in {None, ""}
]

await search_service.bulk_create_search_indices(nodes_to_index)
await search_service.commit_indices()
```

This enables fuzzy matching on node names and file paths for agent tools like `get_code_from_probable_node_name`. The search indices are stored in a separate PostgreSQL table and provide fast substring matching capabilities.

**Sources:** [app/modules/parsing/knowledge_graph/inference_service.py:756-777]()

---

## Phase 6: AI Enhancement

### Inference Service Architecture

`InferenceService.run_inference()` enriches the code graph with AI-generated docstrings and embeddings.

```mermaid
graph TB
    subgraph "1. Node Fetching"
        A["InferenceService.run_inference()"]
        B["fetch_graph() from Neo4j"]
        C["Returns list of node dicts"]
    end
    
    subgraph "2. Batch Preparation"
        D["batch_nodes() with cache checking"]
        E{"Content cacheable?"}
        F["InferenceCacheService.get_cached_inference()"]
        G{"Cache hit?"}
        H["Skip node - use cached data"]
        I["Add to LLM batch"]
    end
    
    subgraph "3. LLM Processing"
        J["Parallel processing with semaphore"]
        K["generate_docstrings() per batch"]
        L["ProviderService.call_llm_with_structured_output()"]
        M["Returns DocstringResponse"]
    end
    
    subgraph "4. Embedding Generation"
        N["SentenceTransformer all-MiniLM-L6-v2"]
        O["Generate 384-dim embedding"]
    end
    
    subgraph "5. Neo4j Update"
        P["Update node properties"]
        Q["SET n.docstring = $docstring"]
        Q2["SET n.embedding = $embedding"]
        R["InferenceCacheService.store_cached_inference()"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E -->|Yes| F
    E -->|No| I
    F --> G
    G -->|Yes| H
    G -->|No| I
    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P
    P --> Q
    Q --> Q2
    Q2 --> R
```

**Sources:** [app/modules/parsing/knowledge_graph/inference_service.py:741-875]()

---

### Batching with Cache Awareness

`batch_nodes()` optimizes LLM API usage through intelligent batching and caching:

**Token-Based Batching** [inference_service.py:352-587]():

1. **Content Hash Generation**: Generate MD5 hash of node text content
2. **Cache Lookup**: Check `InferenceCacheService` for existing inference
3. **Cache Hit**: Store cached docstring in node, skip LLM processing
4. **Cache Miss**: Add node to batch, respecting token limits (default 16K tokens)
5. **Large Node Handling**: Split nodes exceeding token limit into chunks

**Cache Hit Rate Logging** [inference_service.py:560-578]():

```python
cache_hits = 123
cache_misses = 456
uncacheable_nodes = 78
total_nodes = cache_hits + cache_misses + uncacheable_nodes

cache_hit_rate = (cache_hits / total_nodes) * 100  # e.g., 21.0%
logger.info(f"Cache hit rate: {cache_hit_rate:.1f}%")
```

This provides visibility into cache effectiveness across repository re-parses.

**Sources:** [app/modules/parsing/knowledge_graph/inference_service.py:352-587]()

---

### Parallel LLM Requests

Inference requests execute in parallel with a configurable semaphore to respect rate limits:

**Parallel Processing Configuration** [inference_service.py:57]():
```python
self.parallel_requests = int(os.getenv("PARALLEL_REQUESTS", 50))
semaphore = asyncio.Semaphore(self.parallel_requests)
```

**Batch Processing Loop** [inference_service.py:819-859]():

```python
async def process_batch(batch, batch_index: int):
    async with semaphore:
        logger.info(f"Processing batch {batch_index} for project {repo_id}")
        response = await self.generate_response(batch, repo_id)
        
        if isinstance(response, DocstringResponse):
            for request, docstring_result in zip(batch, response.docstrings):
                # Store in cache if node marked for caching
                if request.metadata.get("should_cache"):
                    cache_service.store_cached_inference(
                        content_hash=request.metadata["content_hash"],
                        docstring=docstring_result.docstring,
                        tags=docstring_result.tags
                    )
                
                # Update Neo4j with docstring and embedding
                embedding = embedding_model.encode(docstring_result.docstring)
                await update_neo4j_node(
                    node_id=request.node_id,
                    docstring=docstring_result.docstring,
                    embedding=embedding.tolist()
                )

tasks = [process_batch(batch, i) for i, batch in enumerate(batches)]
results = await asyncio.gather(*tasks)
```

With `PARALLEL_REQUESTS=50`, the system can process 50 batches simultaneously, significantly reducing total inference time for large repositories.

**Sources:** [app/modules/parsing/knowledge_graph/inference_service.py:817-859]()

---

### Embedding Generation

`SentenceTransformer` generates semantic embeddings for vector similarity search:

**Model Configuration** [inference_service.py:35-42]():

```python
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading SentenceTransformer model (first time only)")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        logger.info("SentenceTransformer model loaded successfully")
    return _embedding_model
```

The model is loaded once as a singleton to avoid repeated downloads and initialization overhead.

**Embedding Properties**:
- Model: `all-MiniLM-L6-v2`
- Dimensions: 384
- Device: CPU (configurable)
- Input: Docstring text
- Output: Float vector `[0.123, -0.456, ...]`

Embeddings enable semantic code search via Neo4j vector similarity queries.

**Sources:** [app/modules/parsing/knowledge_graph/inference_service.py:35-54](), [app/modules/parsing/knowledge_graph/inference_service.py:823-859]()

---

## Status Tracking

### Project Status Enum

Projects progress through six status states tracked in PostgreSQL:

| Status | Value | Description | Set By |
|--------|-------|-------------|--------|
| **SUBMITTED** | `"SUBMITTED"` | Parsing task queued in Celery | `ParsingController` |
| **CLONED** | `"CLONED"` | Repository downloaded locally | `ParseHelper` |
| **PARSED** | `"PARSED"` | Neo4j graph created | `CodeGraphService` |
| **READY** | `"READY"` | Inference complete, graph queryable | `InferenceService` |
| **ERROR** | `"ERROR"` | Parsing failed at any stage | Exception handlers |

**Status Transition Flow**:
```
SUBMITTED → CLONED → PARSED → READY
     ↓          ↓        ↓        
   ERROR ← ── ERROR ← ERROR
```

**Sources:** [app/modules/projects/projects_schema.py](), [app/modules/parsing/graph_construction/parsing_service.py:205-285]()

---

### Status Polling Endpoint

Clients poll `GET /api/v1/parse/status/{project_id}` to track parsing progress:

**Response Format** [parsing_controller.py:307-343]():

```json
{
  "status": "PARSED",
  "latest": false
}
```

**Fields**:
- `status`: Current `ProjectStatusEnum` value (SUBMITTED, CLONED, PARSED, READY, ERROR)
- `latest`: Boolean indicating if project is at latest commit (compared to remote HEAD via `ParseHelper.check_commit_status()`)

**Access Control** [parsing_controller.py:311-325]():

The endpoint allows access if:
- Project belongs to requesting user (`Project.user_id == user["user_id"]`), OR
- Project is associated with a PUBLIC conversation (`Conversation.visibility == Visibility.PUBLIC`), OR
- Project is shared with user's email (`Conversation.shared_with_emails.any(user["email"])`)

This enables status checks for shared projects without exposing private project information.

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:307-343]()

---

### Commit Status Checking

`ParseHelper.check_commit_status()` determines if a parsed project matches the latest remote commit:

**Commit Comparison Logic** [parsing_helper.py:868-959]():

1. Get project details from PostgreSQL: `repo_name`, `branch_name`, `commit_id` [lines 875-882]()
2. Fetch remote repository via `CodeProviderService.get_repo()` [line 889]()
3. Get latest commit SHA from remote branch using `repo.get_branch(branch_name).commit.sha` [lines 896-900]()
4. Compare stored `commit_id` with remote commit SHA:
   - If `requested_commit_id` provided: Compare with that instead of remote HEAD [lines 906-911]()
   - Otherwise: Compare stored commit with remote HEAD [lines 918-923]()
5. Return `True` if match, `False` if diverged

This check triggers re-parsing when repository updates are detected, ensuring the knowledge graph stays synchronized with the codebase.

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:868-959]()

---

## Error Handling

### Exception Hierarchy

The parsing pipeline uses typed exceptions for granular error handling:

| Exception | Inherits From | Raised When | Handler Action | File |
|-----------|---------------|-------------|----------------|------|
| `ParsingServiceError` | `Exception` | Base exception | Log and return 500 | parsing_helper.py:26-27 |
| `ParsingFailedError` | `ParsingServiceError` | Parsing logic failure | Set status=ERROR, notify Slack | parsing_helper.py:30-31 |
| `ProjectServiceError` | `Exception` | Project DB operation fails | Rollback transaction | projects_service.py:15-16 |
| `ProjectNotFoundError` | `ProjectServiceError` | Project doesn't exist | Return 404 | projects_service.py:19-20 |

**Usage Examples**:
- `ParsingFailedError` raised when tarball download fails [parsing_helper.py:369]()
- `ParsingFailedError` raised when language detection returns "other" [parsing_service.py:383-385]()
- `ProjectServiceError` raised when project ownership mismatch detected [projects_service.py:110]()

**Sources:** [app/modules/parsing/graph_construction/parsing_helper.py:26-31](), [app/modules/projects/projects_service.py:15-20]()

---

### Error Recovery

**Database Rollback** [parsing_service.py:226-261]():

```python
except Exception as e:
    # Log the full traceback server-side for debugging
    tb_str = "".join(traceback.format_exception(None, e, e.__traceback__))
    logger.exception("Error during parsing", project_id=project_id, user_id=user_id)
    logger.error(f"Full traceback:\n{tb_str}", project_id=project_id, user_id=user_id)
    
    # Rollback the database session to clear any pending transactions
    self.db.rollback()
    
    try:
        await project_manager.update_project_status(project_id, ProjectStatusEnum.ERROR)
    except Exception:
        logger.exception("Failed to update project status after error")
```

**Slack Notifications** [parsing_service.py:220-222]():

Critical errors trigger Slack webhook notifications when not in library mode:
```python
if not self._raise_library_exceptions:
    await ParseWebhookHelper().send_slack_notification(project_id, message)
```

**Library Mode** [parsing_service.py:252-255]():

When `_raise_library_exceptions=True` (for library usage), the service raises `ParsingServiceError` instead of `HTTPException`, allowing the calling library to handle errors appropriately.

**Sources:** [app/modules/parsing/graph_construction/parsing_service.py:214-261]()

---

### Cleanup on Failure

**Neo4j Cleanup** [parsing_service.py:138-160]():

When `cleanup_graph=True`, existing graph data is deleted before re-parsing:

```python
if cleanup_graph:
    neo4j_config = self._get_neo4j_config()
    
    try:
        code_graph_service = CodeGraphService(
            neo4j_config["uri"],
            neo4j_config["username"],
            neo4j_config["password"],
            self.db
        )
        code_graph_service.cleanup_graph(str(project_id))
    except Exception:
        logger.exception("Error in cleanup_graph", project_id=project_id, user_id=user_id)
        if self._raise_library_exceptions:
            raise ParsingServiceError("Failed to cleanup graph")
        raise HTTPException(status_code=500, detail="Internal server error")
```

The `cleanup_graph()` method runs a Cypher query: `MATCH (n {repoId: $project_id}) DETACH DELETE n` [code_graph_service.py:166-174]() and also cleans up the search index via `SearchService.delete_project_index()` [code_graph_service.py:177-178]().

**Filesystem Cleanup** [parsing_service.py:263-273]():

Downloaded repositories are always deleted after parsing (success or failure):

```python
finally:
    project_path = os.getenv("PROJECT_PATH")
    if (extracted_dir 
        and isinstance(extracted_dir, str) 
        and os.path.exists(extracted_dir)
        and project_path
        and extracted_dir.startswith(project_path)):
        shutil.rmtree(extracted_dir, ignore_errors=True)
```

**Sources:** [app/modules/parsing/graph_construction/parsing_service.py:138-273](), [app/modules/parsing/graph_construction/code_graph_service.py:166-178]()

---

## Performance Characteristics

### Typical Parsing Times

Based on repository size (lines of code):

| Repository Size | Node Count | Parsing Time | Inference Time | Total Time |
|-----------------|------------|--------------|----------------|------------|
| Small (< 10K LOC) | 500-1000 | 30-60 sec | 1-2 min | 2-3 min |
| Medium (10K-50K LOC) | 1000-5000 | 1-3 min | 3-8 min | 5-10 min |
| Large (50K-200K LOC) | 5000-20000 | 3-10 min | 10-30 min | 15-40 min |
| Very Large (> 200K LOC) | 20000+ | 10-30 min | 30-120 min | 60-180 min |

**Bottlenecks**:
1. **tree-sitter parsing**: O(n) on file count and size
2. **LLM inference**: O(n) on node count, rate-limited by API
3. **Embedding generation**: O(n) on node count, CPU-bound

**Optimizations**:
- Batch Neo4j writes (1000 nodes/relationships per transaction)
- Parallel LLM requests (configurable via `PARALLEL_REQUESTS`)
- Inference caching (content-hash based, cross-repository)
- Singleton embedding model (avoids repeated loads)

**Sources:** Based on analysis of [app/modules/parsing/graph_construction/code_graph_service.py](), [app/modules/parsing/knowledge_graph/inference_service.py]()

---

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `isDevelopmentMode` | - | Enable local repository parsing |
| `PROJECT_PATH` | `"projects/"` | Directory for downloaded repositories |
| `PARALLEL_REQUESTS` | `50` | Concurrent LLM inference requests |
| `CODE_PROVIDER` | `"github"` | Provider type: github, gitbucket, gitlab |
| `CODE_PROVIDER_BASE_URL` | - | Base URL for self-hosted Git servers |
| `CODE_PROVIDER_TOKEN` | - | Authentication token for Git provider |
| `GITBUCKET_USERNAME` | - | Username for GitBucket Basic Auth fallback |
| `GITBUCKET_PASSWORD` | - | Password for GitBucket Basic Auth fallback |
| `REPO_MANAGER_ENABLED` | `"false"` | Enable RepoManager for advanced features |

**Sources:** [app/modules/parsing/graph_construction/parsing_controller.py:67-87](), [app/modules/parsing/graph_construction/parsing_helper.py:43-52](), [app/modules/parsing/knowledge_graph/inference_service.py:57]()

---

## Related Systems

- **Neo4j Graph Structure** [#4.3](): Detailed schema, node types, relationship types, and query patterns
- **Inference and Docstring Generation** [#4.2](): LLM prompt engineering, cache strategy, embedding model details
- **Code Provider System** [#4.4](): Multi-provider authentication, fallback chains, GitHub App vs PAT
- **Celery Task System** [#9.1](): Task routing, worker configuration, retry policies
- **Project Service** [#6.1](): Project lifecycle, status management, database schema