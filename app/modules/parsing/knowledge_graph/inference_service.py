import asyncio
import os
import re
import time
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

import tiktoken
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.core.config_provider import config_provider
from app.core.database import get_db
from app.modules.intelligence.provider.provider_service import (
    ProviderService,
)
from app.modules.parsing.knowledge_graph.inference_schema import (
    DocstringNode,
    DocstringRequest,
    DocstringResponse,
)
from app.modules.parsing.services.inference_cache_service import InferenceCacheService
from app.modules.parsing.utils.content_hash import (
    generate_content_hash,
    is_content_cacheable,
)
from app.modules.projects.projects_schema import ProjectStatusEnum
from app.modules.projects.projects_service import ProjectService
from app.modules.search.search_service import SearchService
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Match GPT-4o / GitHub Copilot API token counting (o200k_base), not cl100k_base.
INFERENCE_TOKEN_COUNT_MODEL = "gpt-4o"

DOCSTRING_INFERENCE_SYSTEM_MESSAGE = (
    "You are an expert software documentation assistant. You will analyze code "
    "and provide structured documentation in JSON format."
)

# Shared with generate_response — must stay byte-identical to the user message
# skeleton (before code_snippets are inserted) for accurate batch sizing.
DOCSTRING_INFERENCE_USER_PROMPT_TEMPLATE = dedent("""
    You are a senior software engineer with expertise in code analysis and documentation. Your task is to generate concise docstrings for each code snippet and tagging it based on its purpose. Approach this task methodically, following these steps:

    1. **Node Identification**:
    - Carefully parse the provided `code_snippets` to identify each `node_id` and its corresponding code block.
    - Ensure that every `node_id` present in the `code_snippets` is accounted for and processed individually.

    2. **For Each Node**:
    Perform the following tasks for every identified `node_id` and its associated code:

    You are a software engineer tasked with generating concise docstrings for each code snippet and tagging it based on its purpose.

    **Instructions**:
    2.1. **Identify Code Type**:
    - Determine whether each code snippet is primarily **backend** or **frontend**.
    - Use common indicators:
        - **Backend**: Handles database interactions, API endpoints, configuration, or server-side logic.
        - **Frontend**: Contains UI components, event handling, state management, or styling.

    2.2. **Summarize the Purpose**:
    - Based on the identified type, write a brief (1-2 sentences) summary of the code's main purpose and functionality.
    - Focus on what the code does, its role in the system, and any critical operations it performs.
    - If the code snippet is related to **specific roles** like authentication, database access, or UI component, state management, explicitly mention this role.

    2.3. **Assign Tags Based on Code Type**:
    - Use these specific tags based on whether the code is identified as backend or frontend:

    **Backend Tags**:
        - **AUTH**: Handles authentication or authorization.
        - **DATABASE**: Interacts with databases.
        - **API**: Defines API endpoints.
        - **UTILITY**: Provides helper or utility functions.
        - **PRODUCER**: Sends messages to a queue or topic.
        - **CONSUMER**: Processes messages from a queue or topic.
        - **EXTERNAL_SERVICE**: Integrates with external services.
        - **CONFIGURATION**: Manages configuration settings.

    **Frontend Tags**:
        - **UI_COMPONENT**: Renders a visual component in the UI.
        - **FORM_HANDLING**: Manages form data submission and validation.
        - **STATE_MANAGEMENT**: Manages application or component state.
        - **DATA_BINDING**: Binds data to UI elements.
        - **ROUTING**: Manages frontend navigation.
        - **EVENT_HANDLING**: Handles user interactions.
        - **STYLING**: Applies styling or theming.
        - **MEDIA**: Manages media, like images or video.
        - **ANIMATION**: Defines animations in the UI.
        - **ACCESSIBILITY**: Implements accessibility features.
        - **DATA_FETCHING**: Fetches data for frontend use.

    Your response must be a valid JSON object containing a list of docstrings, where each docstring object has:
    - node_id: The ID of the node being documented
    - docstring: A concise description of the code's purpose and functionality
    - tags: A list of relevant tags from the categories above

    Here are the code snippets:

    {code_snippets}
""").strip()


# Global singleton for SentenceTransformer to avoid reloading
_embedding_model = None
_embedding_model_lock = __import__("threading").Lock()


def get_embedding_model():
    """Get the singleton SentenceTransformer model, loading it only once per process.
    Thread-safe via double-checked locking."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _embedding_model_lock:
        if _embedding_model is None:
            logger.info("Loading SentenceTransformer model (first time only)")
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            logger.info("SentenceTransformer model loaded successfully")
    return _embedding_model


def preload_embedding_model() -> bool:
    """
    Load and cache the embedding model in the current process.
    Call this at worker/process startup to avoid mid-task memory spikes
    (e.g. when semantic search runs without LocalServer).
    Returns True if the model was loaded or already cached, False on error.
    """
    try:
        get_embedding_model()
        return True
    except Exception as e:
        logger.warning("Failed to preload embedding model: %s", e)
        return False


class InferenceService:
    def __init__(self, db: Session, user_id: Optional[str] = "dummy"):
        neo4j_config = config_provider.get_neo4j_config()
        self.driver = GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["username"], neo4j_config["password"]),
        )

        self.db = db
        self.provider_service = ProviderService(db, user_id if user_id else "dummy")
        self.embedding_model = get_embedding_model()  # Use singleton to avoid reloading
        self.search_service = SearchService(db)
        self.project_manager = ProjectService(db)
        self.parallel_requests = int(os.getenv("PARALLEL_REQUESTS", 0))
        if self.parallel_requests == 0:
            # Auto-detect based on provider
            auth_provider = self.provider_service.inference_config.auth_provider
            if auth_provider == "github_copilot":
                # GitHub Copilot: conservative to stay under 150 req/min rate limit
                self.parallel_requests = int(os.getenv("GITHUB_COPILOT_PARALLEL_REQUESTS", 5))
                logger.info(f"Using GitHub Copilot with parallel_requests={self.parallel_requests} (rate limit: 150 req/min)")
            elif auth_provider in ["anthropic", "openai"]:
                self.parallel_requests = int(os.getenv("OPENAI_PARALLEL_REQUESTS", 20))
                logger.info(f"Using {auth_provider} with parallel_requests={self.parallel_requests}")
            else:
                self.parallel_requests = 10
                logger.info(f"Using {auth_provider} with parallel_requests={self.parallel_requests}")
        logger.info(f"Inference service initialized with parallel_requests={self.parallel_requests}")

    def close(self):
        self.driver.close()

    def _get_cache_service(self) -> Optional[InferenceCacheService]:
        """Get cache service using the instance's DB session."""
        try:
            return InferenceCacheService(self.db)
        except Exception as e:
            logger.warning(f"Failed to initialize cache service: {e}")
            return None

    def _normalize_node_text(
        self, text: str, node_dict: Dict[str, Dict[str, Any]]
    ) -> str:
        """
        Normalize node text by resolving references for consistent hashing.

        This ensures the same code content produces the same hash across parses,
        even if referenced nodes have different node_ids.
        """
        if text is None:
            return ""

        pattern = r"Code replaced for brevity\. See node_id ([a-f0-9]+)"
        regex = re.compile(pattern)

        def replace_match(match):
            node_id = match.group(1)
            if node_id in node_dict and node_dict[node_id].get("text"):
                # Return full text of referenced node for consistent cache hashing
                return node_dict[node_id]["text"]
            else:
                # Normalize unresolved references to remove node_id dependency
                return "Code replaced for brevity. See node_id <REFERENCE>"

        previous_text = None
        current_text = text

        # Recursively resolve nested references
        while previous_text != current_text:
            previous_text = current_text
            current_text = regex.sub(replace_match, current_text)

        return current_text

    def _lookup_cache_for_nodes(
        self,
        nodes: List[Dict],
        node_dict: Dict[str, Dict[str, Any]],
        cache_service: InferenceCacheService,
        project_id: str,
    ) -> Dict[str, Any]:
        """
        Look up cache for all nodes and mark them with cache hit/miss status.

        Mutates nodes in place, adding:
        - cached_inference: The cached inference data (if hit)
        - content_hash: The hash of normalized content
        - should_cache: Whether to cache the inference result
        - normalized_text: The normalized text for LLM processing

        Returns cache statistics.
        """
        cache_hits = 0
        cache_misses = 0
        uncacheable_nodes = 0
        cache_lookup_time = 0.0

        lookup_start = time.time()

        for node in nodes:
            text = node.get("text")
            if not text:
                continue

            # Normalize text for consistent hashing
            normalized_text = self._normalize_node_text(text, node_dict)
            node["normalized_text"] = normalized_text

            # Check if content is cacheable
            if not is_content_cacheable(normalized_text):
                uncacheable_nodes += 1
                continue

            # Generate content hash
            content_hash = generate_content_hash(normalized_text, node.get("node_type"))
            node["content_hash"] = content_hash

            # Look up in cache
            node_lookup_start = time.time()
            cached_inference = cache_service.get_cached_inference(content_hash)
            cache_lookup_time += time.time() - node_lookup_start

            if cached_inference:
                # Cache hit - store the inference data on the node
                node["cached_inference"] = cached_inference
                cache_hits += 1
                # Verify the assignment worked
                if not node.get("cached_inference"):
                    logger.error(
                        f"CACHE BUG: cached_inference not set after assignment! node={node['node_id'][:8]}"
                    )
                logger.debug(
                    f"✅ CACHE HIT | node={node['node_id'][:8]} | "
                    f"hash={content_hash[:12]} | type={node.get('node_type', 'UNKNOWN')}"
                )
            else:
                # Cache miss - mark for caching after LLM inference
                node["should_cache"] = True
                cache_misses += 1
                logger.debug(
                    f"❌ CACHE MISS | node={node['node_id'][:8]} | "
                    f"hash={content_hash[:12]} | type={node.get('node_type', 'UNKNOWN')}"
                )

        total_lookup_time = time.time() - lookup_start
        total_cacheable = cache_hits + cache_misses
        hit_rate = (cache_hits / total_cacheable * 100) if total_cacheable > 0 else 0

        logger.info(
            f"[CACHE LOOKUP] Completed cache lookup for {len(nodes)} nodes: "
            f"Hits: {cache_hits} ({hit_rate:.1f}%), Misses: {cache_misses}, "
            f"Uncacheable: {uncacheable_nodes}, Total time: {total_lookup_time:.2f}s",
            project_id=project_id,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            uncacheable_nodes=uncacheable_nodes,
            cache_hit_rate=hit_rate,
        )

        return {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "uncacheable_nodes": uncacheable_nodes,
            "total_nodes": len(nodes),
            "cache_lookup_time": cache_lookup_time,
            "cache_hit_rate": hit_rate,
        }

    def _store_inference_in_cache(
        self,
        cache_service: InferenceCacheService,
        content_hash: str,
        docstring: str,
        tags: List[str],
        embedding: List[float],
        project_id: str,
        node_type: Optional[str] = None,
        content_length: Optional[int] = None,
    ) -> bool:
        """Store inference result in cache. Returns True if successful."""
        try:
            inference_data = {
                "docstring": docstring,
                "tags": tags,
            }
            cache_service.store_inference(
                content_hash=content_hash,
                inference_data=inference_data,
                project_id=project_id,
                node_type=node_type,
                content_length=content_length,
                embedding_vector=embedding,
                tags=tags,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to store inference in cache: {e}")
            return False

    def log_graph_stats(self, repo_id):
        query = """
        MATCH (n:NODE {repoId: $repo_id})
        OPTIONAL MATCH (n)-[r]-(m:NODE {repoId: $repo_id})
        RETURN
        COUNT(DISTINCT n) AS nodeCount,
        COUNT(DISTINCT r) AS relationshipCount
        """

        try:
            # Establish connection
            with self.driver.session() as session:
                # Execute the query
                result = session.run(query, repo_id=repo_id)
                record = result.single()

                if record:
                    node_count = record["nodeCount"]
                    relationship_count = record["relationshipCount"]

                    # Log the results
                    logger.info(
                        f"DEBUGNEO4J: Repo ID: {repo_id}, Nodes: {node_count}, Relationships: {relationship_count}"
                    )
                else:
                    logger.info(
                        f"DEBUGNEO4J: No data found for repository ID: {repo_id}"
                    )

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")

    # Class-level cache for tiktoken encodings
    _encoding_cache: Dict[str, Any] = {}

    def num_tokens_from_string(self, string: str, model: str = "gpt-4") -> int:
        """Returns the number of tokens in a text string."""
        # Handle None or empty strings gracefully
        if string is None:
            return 0
        if not isinstance(string, str):
            logger.warning(
                f"Expected string, got {type(string)}. Converting to string."
            )
            string = str(string)

        # Cache the encoding to avoid repeated model lookups
        if model not in InferenceService._encoding_cache:
            try:
                InferenceService._encoding_cache[model] = tiktoken.encoding_for_model(
                    model
                )
            except KeyError:
                logger.warning("Warning: model not found. Using cl100k_base encoding.")
                InferenceService._encoding_cache[model] = tiktoken.get_encoding(
                    "cl100k_base"
                )

        encoding = InferenceService._encoding_cache[model]
        return len(encoding.encode(string, disallowed_special=set()))

    def fetch_graph(self, repo_id: str) -> List[Dict]:
        batch_size = 500
        all_nodes = []
        with self.driver.session() as session:
            offset = 0
            while True:
                result = session.run(
                    "MATCH (n:NODE {repoId: $repo_id}) "
                    "RETURN n.node_id AS node_id, n.text AS text, n.file_path AS file_path, n.start_line AS start_line, n.end_line AS end_line, n.name AS name "
                    "SKIP $offset LIMIT $limit",
                    repo_id=repo_id,
                    offset=offset,
                    limit=batch_size,
                )
                batch = [dict(record) for record in result]
                if not batch:
                    break
                all_nodes.extend(batch)
                offset += batch_size

        logger.info(f"DEBUGNEO4J: Fetched {len(all_nodes)} nodes for repo {repo_id}")
        return all_nodes

    def get_entry_points(self, repo_id: str) -> List[str]:
        batch_size = 400  # Define the batch size
        all_entry_points = []
        with self.driver.session() as session:
            offset = 0
            while True:
                result = session.run(
                    f"""
                    MATCH (f:FUNCTION)
                    WHERE f.repoId = '{repo_id}'
                    AND NOT ()-[:CALLS]->(f)
                    AND (f)-[:CALLS]->()
                    RETURN f.node_id as node_id
                    SKIP $offset LIMIT $limit
                    """,
                    offset=offset,
                    limit=batch_size,
                )
                batch = result.data()
                if not batch:
                    break
                all_entry_points.extend([record["node_id"] for record in batch])
                offset += batch_size
        return all_entry_points

    def get_neighbours(self, node_id: str, repo_id: str):
        with self.driver.session() as session:
            batch_size = 400  # Define the batch size
            all_nodes_info = []
            offset = 0
            while True:
                result = session.run(
                    """
                    MATCH (start {node_id: $node_id, repoId: $repo_id})
                    OPTIONAL MATCH (start)-[:CALLS]->(direct_neighbour)
                    OPTIONAL MATCH (start)-[:CALLS]->()-[:CALLS*0..]->(indirect_neighbour)
                    WITH start, COLLECT(DISTINCT direct_neighbour) + COLLECT(DISTINCT indirect_neighbour) AS all_neighbours
                    UNWIND all_neighbours AS neighbour
                    WITH start, neighbour
                    WHERE neighbour IS NOT NULL AND neighbour <> start
                    RETURN DISTINCT neighbour.node_id AS node_id, neighbour.name AS function_name, labels(neighbour) AS labels
                    SKIP $offset LIMIT $limit
                    """,
                    node_id=node_id,
                    repo_id=repo_id,
                    offset=offset,
                    limit=batch_size,
                )
                batch = result.data()
                if not batch:
                    break
                all_nodes_info.extend(
                    [
                        record["node_id"]
                        for record in batch
                        if "FUNCTION" in record["labels"]
                    ]
                )
                offset += batch_size
            return all_nodes_info

    def get_entry_points_for_nodes(
        self, node_ids: List[str], repo_id: str
    ) -> Dict[str, List[str]]:
        with self.driver.session() as session:
            result = session.run(
                """
                UNWIND $node_ids AS nodeId
                MATCH (n:FUNCTION)
                WHERE n.node_id = nodeId and n.repoId = $repo_id
                OPTIONAL MATCH path = (entryPoint)-[*]->(n)
                WHERE NOT (entryPoint)<--()
                RETURN n.node_id AS input_node_id, collect(DISTINCT entryPoint.node_id) AS entry_point_node_ids

                """,
                node_ids=node_ids,
                repo_id=repo_id,
            )
            return {
                record["input_node_id"]: (
                    record["entry_point_node_ids"]
                    if len(record["entry_point_node_ids"]) > 0
                    else [record["input_node_id"]]
                )
                for record in result
            }

    def split_large_node(
        self, node_text: str, node_id: str, max_tokens: int
    ) -> List[Dict[str, Any]]:
        """
        Split large nodes into processable chunks with context preservation.

        Uses incremental token counting for O(n) performance instead of O(n²).
        """
        model = "gpt-4"
        max_chunk_tokens = max_tokens // 2  # Reserve space for prompt

        lines = node_text.split("\n")
        chunks = []
        current_chunk_lines = []
        current_tokens = 0

        # Token overhead for newlines (approximately 1 token per newline)
        NEWLINE_OVERHEAD = 1

        for line in lines:
            # Count tokens for just this line (O(1) per line instead of O(n))
            line_tokens = self.num_tokens_from_string(line, model)

            # Estimate total: current + new line + newline overhead
            estimated_total = current_tokens + line_tokens + NEWLINE_OVERHEAD

            if estimated_total > max_chunk_tokens and current_chunk_lines:
                # Save current chunk and start new one
                chunks.append(
                    {
                        "text": "\n".join(current_chunk_lines),
                        "node_id": f"{node_id}_chunk_{len(chunks)}",
                        "is_chunk": True,
                        "parent_node_id": node_id,
                        "chunk_index": len(chunks),
                    }
                )
                current_chunk_lines = [line]
                current_tokens = line_tokens
            else:
                current_chunk_lines.append(line)
                current_tokens = estimated_total

        # Add final chunk
        if current_chunk_lines:
            chunks.append(
                {
                    "text": "\n".join(current_chunk_lines),
                    "node_id": f"{node_id}_chunk_{len(chunks)}",
                    "is_chunk": True,
                    "parent_node_id": node_id,
                    "chunk_index": len(chunks),
                }
            )

        return chunks

    def consolidate_chunk_responses(
        self, chunk_responses: List[DocstringResponse], parent_node_id: str
    ) -> DocstringResponse:
        """Consolidate multiple chunk docstring responses into a single parent node response"""
        if not chunk_responses:
            return DocstringResponse(docstrings=[])

        # Collect all chunk docstrings
        all_docstrings = []
        all_tags = set()

        for response in chunk_responses:
            for docstring in response.docstrings:
                all_docstrings.append(docstring.docstring)
                all_tags.update(docstring.tags or [])

        # Create consolidated docstring
        if len(all_docstrings) == 1:
            consolidated_text = all_docstrings[0]
        else:
            # Combine multiple chunk descriptions intelligently
            consolidated_text = f"This is a large code component split across {len(all_docstrings)} sections: "
            consolidated_text += " | ".join(
                [f"Section {i + 1}: {doc}" for i, doc in enumerate(all_docstrings)]
            )

        # Create single consolidated docstring for parent node
        from app.modules.parsing.knowledge_graph.inference_schema import DocstringNode

        consolidated_docstring = DocstringNode(
            node_id=parent_node_id, docstring=consolidated_text, tags=list(all_tags)
        )

        return DocstringResponse(docstrings=[consolidated_docstring])

    def process_chunk_responses(
        self, response: DocstringResponse, batch: List[DocstringRequest]
    ) -> Optional[DocstringResponse]:
        """Process chunk responses and consolidate them by parent node"""
        # Separate chunk responses from regular responses
        chunk_responses = {}
        regular_responses = []

        for docstring in response.docstrings:
            # Find the corresponding request to get metadata
            request = next(
                (req for req in batch if req.node_id == docstring.node_id), None
            )
            if request and request.metadata and request.metadata.get("is_chunk"):
                parent_id = request.metadata.get("parent_node_id")
                if parent_id:
                    if parent_id not in chunk_responses:
                        chunk_responses[parent_id] = []
                    chunk_responses[parent_id].append(docstring)
            else:
                regular_responses.append(docstring)

        # If no chunks, return original response
        if not chunk_responses:
            return response

        # Consolidate chunk responses
        consolidated_responses = []

        for parent_id, chunk_docstrings in chunk_responses.items():
            # Create a mock response list for consolidation
            mock_responses = []
            for chunk_doc in chunk_docstrings:
                from app.modules.parsing.knowledge_graph.inference_schema import (
                    DocstringResponse,
                )

                mock_responses.append(DocstringResponse(docstrings=[chunk_doc]))

            consolidated = self.consolidate_chunk_responses(mock_responses, parent_id)
            consolidated_responses.extend(consolidated.docstrings)

        # Add regular (non-chunk) responses
        consolidated_responses.extend(regular_responses)

        return DocstringResponse(docstrings=consolidated_responses)

    def _get_inference_max_tokens(self) -> int:
        """Return the max input tokens budget for inference batches.

        For providers with independent input/output limits (e.g. github_copilot),
        the prompt limit is returned directly.  For standard APIs where input and
        output share a combined context window, the output budget is subtracted.
        """
        from app.modules.intelligence.provider.llm_config import get_context_window
        model = self.provider_service.inference_config.model
        model_str = (model or "").strip()
        # github_copilot gateway enforces independent limits:
        #   prompt ≤ 64K, completion ≤ 12K (separate, not a shared pool)
        if model_str == "github_copilot/gpt-4o":
            return 64000
        context_window = get_context_window(model) or 128000
        output_budget  = self._get_inference_effective_output_tokens()
        return max(8192, context_window - output_budget)

    def _create_batches_from_nodes(
        self,
        nodes: List[Dict],
        max_tokens: int = None,
        model: str = "gpt-4",
        project_id: Optional[str] = None,
    ) -> List[List[DocstringRequest]]:
        """
        Filter nodes needing inference, create DocstringRequest objects (splitting
        large nodes into chunks), then delegate packing to _build_batches.
        """
        if max_tokens is None:
            max_tokens = self._get_inference_max_tokens()
        node_dict = {node["node_id"]: node for node in nodes}

        nodes_with_cached = sum(1 for n in nodes if n.get("cached_inference"))
        nodes_needing_inference = [
            n for n in nodes
            if not n.get("cached_inference")
            and n.get("text")
            and (n.get("should_cache") or n.get("content_hash"))
        ]
        nodes_skipped_uncacheable = sum(
            1 for n in nodes
            if not n.get("cached_inference")
            and n.get("text")
            and not n.get("should_cache")
            and not n.get("content_hash")
        )

        logger.info(
            f"[BATCHING] Preparing requests for {len(nodes_needing_inference)} nodes "
            f"(total: {len(nodes)}, cached: {nodes_with_cached}, "
            f"skipped uncacheable: {nodes_skipped_uncacheable})",
            project_id=project_id,
            nodes_total=len(nodes),
            nodes_with_cached=nodes_with_cached,
            nodes_needing_inference=len(nodes_needing_inference),
            nodes_skipped_uncacheable=nodes_skipped_uncacheable,
        )

        requests: List[DocstringRequest] = []
        for node in nodes_needing_inference:
            text = node.get("normalized_text")
            if not text:
                text = self._normalize_node_text(node.get("text", ""), node_dict)
                node["normalized_text"] = text

            node_tokens = self.num_tokens_from_string(text, model)

            if node_tokens > max_tokens:
                logger.debug(
                    f"Node {node['node_id'][:8]} exceeds token limit ({node_tokens}). Splitting..."
                )
                for chunk in self.split_large_node(text, node["node_id"], max_tokens):
                    requests.append(DocstringRequest(
                        node_id=chunk["node_id"],
                        text=chunk["text"],
                        metadata={
                            "is_chunk": True,
                            "parent_node_id": chunk["parent_node_id"],
                            "chunk_index": chunk.get("chunk_index", 0),
                            "should_cache": node.get("should_cache", False),
                            "content_hash": node.get("content_hash"),
                            "node_type": node.get("node_type"),
                            "file_path": node.get("file_path"),
                        },
                    ))
            else:
                requests.append(DocstringRequest(
                    node_id=node["node_id"],
                    text=text,
                    metadata={
                        "should_cache": node.get("should_cache", False),
                        "content_hash": node.get("content_hash"),
                        "node_type": node.get("node_type"),
                        "file_path": node.get("file_path"),
                    },
                ))

        return self._build_batches(requests, project_id=project_id)

    def _get_inference_effective_output_tokens(self) -> int:
        """Max completion tokens for inference calls."""
        max_out = self.provider_service.inference_config.default_params.get("max_tokens")
        if max_out is None:
            max_out = int(os.environ.get("INFERENCE_MAX_OUTPUT_TOKENS", "16384"))
        # github_copilot/gpt-4o caps around 12k despite declared higher limits
        model = (self.provider_service.inference_config.model or "").strip()
        if model == "github_copilot/gpt-4o":
            max_out = min(int(max_out), 12288)
        return max(1024, int(max_out))

    def _build_batches(
        self,
        requests: List[DocstringRequest],
        project_id: Optional[str] = None,
    ) -> List[List[DocstringRequest]]:
        """Single-pass greedy batcher respecting both input and output token budgets.

        Replaces the former two-pass approach (_create_batches_from_nodes +
        _split_batches_for_output_token_budget). Re-used identically for primary
        batching and retry passes.

        max_nodes is derived from both budgets using the actual average snippet size
        of the requests being packed — no hard-coded constant required:
          max_nodes_by_input  = (input_budget  - prompt_overhead) // avg_snippet_tokens
          max_nodes_by_output = (output_budget - JSON_ENVELOPE)   // output_per_node
          max_nodes           = min(max_nodes_by_input, max_nodes_by_output)

        Calibration (device-modeling-language): actual JSON output per returned node
        is 45–86 tokens regardless of snippet size (p50 ≈ 62, p90 ≈ 74). The model
        writes a concise 1–2 sentence docstring, so output does not scale with code
        length. INFERENCE_OUTPUT_TOKENS_PER_NODE=272 targets ~45 nodes/batch.

        Tuning (env vars):
          INFERENCE_OUTPUT_TOKENS_PER_NODE  – estimated completion tokens per node (default 272).
          INFERENCE_MAX_NODES_PER_BATCH     – optional hard override for max_nodes.
        """
        if not requests:
            return []

        input_budget  = self._get_inference_max_tokens()
        output_budget = self._get_inference_effective_output_tokens()

        try:
            output_per_node = max(10, int(os.environ.get("INFERENCE_OUTPUT_TOKENS_PER_NODE", "272")))
        except (TypeError, ValueError):
            output_per_node = 272

        tok_model = INFERENCE_TOKEN_COUNT_MODEL
        # Tokenize the same system + user skeleton generate_response sends (empty snippets).
        prompt_overhead = (
            self.num_tokens_from_string(DOCSTRING_INFERENCE_SYSTEM_MESSAGE, tok_model)
            + self.num_tokens_from_string(
                DOCSTRING_INFERENCE_USER_PROMPT_TEMPLATE.format(code_snippets=""),
                tok_model,
            )
        )
        # Tokens for {"docstrings":[...]} JSON envelope in the structured output
        JSON_ENVELOPE = 20

        # Count tokens exactly as generate_response formats each node in the prompt:
        #   "node_id: {uuid} \n```\n{text}\n```\n\n "
        # Use gpt-4o tokenizer to match Copilot / GPT-4o API counting (o200k_base).
        counts = [
            self.num_tokens_from_string(
                f"node_id: {r.node_id} \n```\n{r.text or ''}\n```\n\n ", tok_model
            )
            for r in requests
        ]

        # Keep a prompt-side safety margin to avoid provider-side tokenization drift
        # causing occasional 64K overruns (Copilot gateway limit).
        try:
            input_safety_margin = max(
                0, int(os.environ.get("INFERENCE_INPUT_SAFETY_MARGIN_TOKENS", "2000"))
            )
        except (TypeError, ValueError):
            input_safety_margin = 2000
        input_pack_budget = max(4096, input_budget - input_safety_margin)

        # Derive max_nodes from both budgets using the actual average snippet size.
        avg_snippet         = max(1, sum(counts) // len(counts))
        max_nodes_by_input  = max(1, (input_pack_budget - prompt_overhead) // avg_snippet)
        max_nodes_by_output = max(1, (output_budget - JSON_ENVELOPE)   // output_per_node)
        max_nodes           = min(max_nodes_by_input, max_nodes_by_output)

        # Allow an explicit hard override via env var.
        raw_override = os.environ.get("INFERENCE_MAX_NODES_PER_BATCH")
        if raw_override is not None:
            try:
                max_nodes = max(1, int(raw_override))
            except (TypeError, ValueError):
                pass

        batches: List[List[DocstringRequest]] = []
        cur: List[DocstringRequest] = []
        cur_in  = prompt_overhead
        cur_out = JSON_ENVELOPE

        for req, node_in in zip(requests, counts):
            needs_flush = bool(cur) and (
                len(cur) >= max_nodes
                or cur_in + node_in  > input_pack_budget
                or cur_out + output_per_node > output_budget
            )
            if needs_flush:
                batches.append(cur)
                cur     = []
                cur_in  = prompt_overhead
                cur_out = JSON_ENVELOPE
            cur.append(req)
            cur_in  += node_in
            cur_out += output_per_node

        if cur:
            batches.append(cur)

        total_nodes = sum(len(b) for b in batches)
        logger.info(
            f"[BATCHING] Created {len(batches)} batches for {total_nodes} nodes "
            f"(max_nodes={max_nodes} [input-derived={max_nodes_by_input}, "
            f"output-derived={max_nodes_by_output}], "
            f"avg_snippet={avg_snippet}, prompt_overhead={prompt_overhead}, "
            f"input_budget={input_budget}, input_pack_budget={input_pack_budget}, "
            f"input_safety_margin={input_safety_margin}, "
            f"output_budget={output_budget}, "
            f"output_per_node={output_per_node}, tok_model={tok_model})",
            project_id=project_id,
            batch_count=len(batches),
            total_batched_nodes=total_nodes,
            max_nodes_per_batch=max_nodes,
            max_nodes_by_input=max_nodes_by_input,
            max_nodes_by_output=max_nodes_by_output,
            avg_snippet_tokens=avg_snippet,
            prompt_overhead_tokens=prompt_overhead,
            input_budget_tokens=input_budget,
            input_pack_budget_tokens=input_pack_budget,
            input_safety_margin_tokens=input_safety_margin,
            output_budget_tokens=output_budget,
            output_per_node_tokens=output_per_node,
            token_count_model=tok_model,
        )
        return batches

    def _actual_docstring_response_json_tokens(
        self, response: DocstringResponse, model: str = INFERENCE_TOKEN_COUNT_MODEL
    ) -> int:
        """Tiktoken count of the structured JSON the model returned (proxy for completion size)."""
        if not response.docstrings:
            return self.num_tokens_from_string('{"docstrings":[]}', model)
        return self.num_tokens_from_string(response.model_dump_json(), model)

    def _inference_output_calibration_log_enabled(self) -> bool:
        raw = os.environ.get("INFERENCE_OUTPUT_CALIBRATION_LOG", "0")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    def _log_inference_output_calibration(
        self,
        batch: List[DocstringRequest],
        result: DocstringResponse,
        repo_id: str,
    ) -> None:
        """Log snippet vs measured JSON output. Enable with INFERENCE_OUTPUT_CALIBRATION_LOG=1."""
        if not self._inference_output_calibration_log_enabled():
            return
        model = INFERENCE_TOKEN_COUNT_MODEL
        snippet_sum = sum(self.num_tokens_from_string(r.text or "", model) for r in batch)
        actual_json = self._actual_docstring_response_json_tokens(result, model=model)
        returned = len(result.docstrings)
        requested = len(batch)
        by_id = {r.node_id: r for r in batch}
        matched = [by_id[d.node_id] for d in result.docstrings if d.node_id in by_id]
        ret_snippet_sum = sum(self.num_tokens_from_string(r.text or "", model) for r in matched)
        doc_text_sum = sum(
            self.num_tokens_from_string(d.docstring or "", model) for d in result.docstrings
        )
        avg_doc_per_snip = (doc_text_sum / ret_snippet_sum) if ret_snippet_sum > 0 else None
        per_node_json    = (actual_json  / returned)        if returned > 0        else None
        logger.info(
            f"[INFERENCE][OUTPUT_CALIB] batch nodes={requested} returned={returned} | "
            f"snippet_tokens_sum={snippet_sum} actual_json_out_tokens={actual_json} | "
            f"per_node_json_tokens={per_node_json} "
            f"avg_docstring_tokens_per_snippet_token={avg_doc_per_snip}",
            project_id=repo_id,
            batch_requested_nodes=requested,
            batch_returned_docstrings=returned,
            snippet_tokens_sum=snippet_sum,
            actual_json_output_tokens=actual_json,
            per_node_json_tokens=per_node_json,
            avg_docstring_tokens_per_snippet_token=avg_doc_per_snip,
        )

    async def generate_docstrings_for_entry_points(
        self,
        all_docstrings,
        entry_points_neighbors: Dict[str, List[str]],
    ) -> Dict[str, DocstringResponse]:
        docstring_lookup = {
            d.node_id: d.docstring for d in all_docstrings["docstrings"]
        }

        entry_point_batches = self.batch_entry_points(
            entry_points_neighbors, docstring_lookup
        )

        semaphore = asyncio.Semaphore(self.parallel_requests)

        async def process_batch(batch):
            async with semaphore:
                response = await self.generate_entry_point_response(batch)
                if isinstance(response, DocstringResponse):
                    return response
                else:
                    return await self.generate_docstrings_for_entry_points(
                        all_docstrings, entry_points_neighbors
                    )

        tasks = [process_batch(batch) for batch in entry_point_batches]
        results = await asyncio.gather(*tasks)

        updated_docstrings = DocstringResponse(docstrings=[])
        for result in results:
            updated_docstrings.docstrings.extend(result.docstrings)

        # Update all_docstrings with the new entry point docstrings
        for updated_docstring in updated_docstrings.docstrings:
            existing_index = next(
                (
                    i
                    for i, d in enumerate(all_docstrings["docstrings"])
                    if d.node_id == updated_docstring.node_id
                ),
                None,
            )
            if existing_index is not None:
                all_docstrings["docstrings"][existing_index] = updated_docstring
            else:
                all_docstrings["docstrings"].append(updated_docstring)

        return all_docstrings

    def batch_entry_points(
        self,
        entry_points_neighbors: Dict[str, List[str]],
        docstring_lookup: Dict[str, str],
        max_tokens: int = 8000,  # input budget per batch; output needs equal headroom
        model: str = "gpt-4",
    ) -> List[List[Dict[str, str]]]:
        batches = []
        current_batch = []
        current_tokens = 0

        for entry_point, neighbors in entry_points_neighbors.items():
            entry_docstring = docstring_lookup.get(entry_point, "")
            neighbor_docstrings = [
                f"{neighbor}: {docstring_lookup.get(neighbor, '')}"
                for neighbor in neighbors
            ]
            flow_description = "\n".join(neighbor_docstrings)

            entry_point_data = {
                "node_id": entry_point,
                "entry_docstring": entry_docstring,
                "flow_description": entry_docstring + "\n" + flow_description,
            }

            entry_point_tokens = self.num_tokens_from_string(
                entry_docstring + flow_description, model
            )

            if entry_point_tokens > max_tokens:
                continue  # Skip entry points that exceed the max_tokens limit

            if current_tokens + entry_point_tokens > max_tokens:
                # Safety check: only append if current_batch has items
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(entry_point_data)
            current_tokens += entry_point_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    async def generate_entry_point_response(
        self, batch: List[Dict[str, str]]
    ) -> DocstringResponse:
        prompt = """
        You are an expert software architect with deep knowledge of distributed systems and cloud-native applications. Your task is to analyze entry points and their function flows in a codebase.

        For each of the following entry points and their function flows, perform the following task:

        1. **Flow Summary**: Generate a concise yet comprehensive summary of the overall intent and purpose of the entry point and its flow. Follow these guidelines:
           - Start with a high-level overview of the entry point's purpose.
           - Detail the main steps or processes involved in the flow.
           - Highlight key interactions with external systems or services.
           - Specify ALL API paths, HTTP methods, topic names, database interactions, and critical function calls.
           - Identify any error handling or edge cases.
           - Conclude with the expected output or result of the flow.

        Remember, the summary should be technical enough for a senior developer to understand the code's functionality via similarity search, but concise enough to be quickly parsed. Aim for a balance between detail and brevity.

        Your response must be a valid JSON object containing a list of docstrings, where each docstring object has:
        - node_id: The ID of the entry point being documented
        - docstring: A comprehensive flow summary following the guidelines above
        - tags: A list of relevant tags based on the functionality (e.g., ["API", "DATABASE"] for endpoints that interact with a database)

        Here are the entry points and their flows:

        {entry_points}
        """

        entry_points_text = "\n\n".join(
            [
                f"Entry point: {entry_point['node_id']}\n"
                f"Flow:\n{entry_point['flow_description']}"
                f"Entry docstring:\n{entry_point['entry_docstring']}"
                for entry_point in batch
            ]
        )

        messages = [
            {
                "role": "system",
                "content": "You are an expert software architecture documentation assistant. You will analyze code flows and provide structured documentation in JSON format.",
            },
            {"role": "user", "content": prompt.format(entry_points=entry_points_text)},
        ]

        try:
            result = await self.provider_service.call_llm_with_structured_output(
                messages=messages,
                output_schema=DocstringResponse,
                config_type="inference",
            )
            return result
        except Exception as e:
            logger.error(f"Entry point response generation failed: {e}")
            return DocstringResponse(docstrings=[])

    async def generate_docstrings(
        self, repo_id: str
    ) -> tuple[Dict[str, DocstringResponse], Dict[str, Any]]:
        inference_start_time = time.time()
        logger.info(
            f"[INFERENCE] Starting docstring generation for project {repo_id}",
            project_id=repo_id,
        )
        self.log_graph_stats(repo_id)

        # Initialize cache service once for the entire inference process
        cache_service = self._get_cache_service()
        if cache_service:
            logger.info(
                "[INFERENCE] Cache service initialized successfully",
                project_id=repo_id,
            )
        else:
            logger.warning(
                "[INFERENCE] Cache service unavailable, proceeding without caching",
                project_id=repo_id,
            )

        # Step 1: Fetch graph nodes
        fetch_start = time.time()
        logger.info(
            f"[INFERENCE] Step 1/6: Fetching graph nodes from Neo4j",
            project_id=repo_id,
        )
        nodes = self.fetch_graph(repo_id)
        fetch_time = time.time() - fetch_start
        logger.info(
            f"[INFERENCE] Fetched {len(nodes)} nodes from graph in {fetch_time:.2f}s",
            project_id=repo_id,
            node_count=len(nodes),
            fetch_time_seconds=fetch_time,
        )
        self.log_graph_stats(repo_id)

        # Step 2: Create search indices
        search_index_start = time.time()
        logger.info(
            f"[INFERENCE] Step 2/6: Creating search indices for {len(nodes)} nodes",
            project_id=repo_id,
            node_count=len(nodes),
        )

        # Prepare a list of nodes for bulk insert
        nodes_to_index = [
            {
                "project_id": repo_id,
                "node_id": node["node_id"],
                "name": node.get("name", ""),
                "file_path": node.get("file_path", ""),
                "content": f"{node.get('name', '')} {node.get('file_path', '')}",
            }
            for node in nodes
            if node.get("file_path") not in {None, ""}
            and node.get("name") not in {None, ""}
        ]

        # Perform bulk insert
        await self.search_service.bulk_create_search_indices(nodes_to_index)
        search_index_time = time.time() - search_index_start
        logger.info(
            f"[INFERENCE] Created search indices over {len(nodes_to_index)} nodes in {search_index_time:.2f}s",
            project_id=repo_id,
            indexed_nodes=len(nodes_to_index),
            search_index_time_seconds=search_index_time,
        )

        commit_start = time.time()
        await self.search_service.commit_indices()
        commit_time = time.time() - commit_start
        logger.info(
            f"[INFERENCE] Committed search indices in {commit_time:.2f}s",
            project_id=repo_id,
            commit_time_seconds=commit_time,
        )

        # Step 3: Cache lookup - check which nodes have cached inference
        cache_lookup_start = time.time()
        logger.info(
            f"[INFERENCE] Step 3/6: Looking up cache for {len(nodes)} nodes",
            project_id=repo_id,
        )

        node_dict = {node["node_id"]: node for node in nodes}
        cache_stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "uncacheable_nodes": 0,
            "total_nodes": len(nodes),
        }

        if cache_service:
            cache_stats = self._lookup_cache_for_nodes(
                nodes, node_dict, cache_service, repo_id
            )
        else:
            # Mark all cacheable nodes for caching when service is available
            for node in nodes:
                if node.get("text"):
                    normalized_text = self._normalize_node_text(
                        node.get("text", ""), node_dict
                    )
                    node["normalized_text"] = normalized_text
                    if is_content_cacheable(normalized_text):
                        node["content_hash"] = generate_content_hash(
                            normalized_text, node.get("node_type")
                        )
                        node["should_cache"] = True
                        cache_stats["cache_misses"] += 1
                    else:
                        cache_stats["uncacheable_nodes"] += 1

        cache_lookup_time = time.time() - cache_lookup_start

        # Verify cache state after lookup
        nodes_with_cached_inference = sum(1 for n in nodes if n.get("cached_inference"))
        nodes_with_should_cache = sum(1 for n in nodes if n.get("should_cache"))

        logger.info(
            f"[INFERENCE] Cache lookup completed in {cache_lookup_time:.2f}s | "
            f"Stats: hits={cache_stats.get('cache_hits', 0)}, misses={cache_stats.get('cache_misses', 0)} | "
            f"Verification: nodes_with_cached_inference={nodes_with_cached_inference}, nodes_with_should_cache={nodes_with_should_cache}",
            project_id=repo_id,
            cache_lookup_time_seconds=cache_lookup_time,
            nodes_with_cached_inference=nodes_with_cached_inference,
            nodes_with_should_cache=nodes_with_should_cache,
        )

        # Step 4: Create batches for nodes that need LLM inference
        batch_start = time.time()
        logger.info(
            f"[INFERENCE] Step 4/6: Creating batches for LLM inference",
            project_id=repo_id,
        )
        batches = self._create_batches_from_nodes(nodes, project_id=repo_id)
        batch_time = time.time() - batch_start
        logger.info(
            f"[INFERENCE] Created {len(batches)} batches in {batch_time:.2f}s",
            project_id=repo_id,
            batch_count=len(batches),
            batch_time_seconds=batch_time,
        )

        # Step 5: Process cached nodes (batch update Neo4j with cached inference)
        cached_process_start = time.time()
        cached_nodes = [node for node in nodes if node.get("cached_inference")]
        logger.info(
            f"[INFERENCE] Step 5/6: Batch processing {len(cached_nodes)} cached nodes",
            project_id=repo_id,
        )

        # Use batch update for much better performance (single DB call instead of N calls)
        cached_updated = self.batch_update_neo4j_with_cached_inference(
            cached_nodes, repo_id
        )

        cached_process_time = time.time() - cached_process_start
        logger.info(
            f"[INFERENCE] Batch processed {cached_updated} cached nodes in {cached_process_time:.2f}s",
            project_id=repo_id,
            cached_nodes_count=cached_updated,
            cached_process_time_seconds=cached_process_time,
        )

        all_docstrings = {"docstrings": []}
        total_cache_stored_count = 0

        # Step 6: Process LLM batches and store results in cache (two-phase design)
        llm_batch_start = time.time()
        logger.info(
            f"[INFERENCE] Step 6/6: Processing {len(batches)} LLM batches",
            project_id=repo_id,
            batch_count=len(batches),
        )

        semaphore = asyncio.Semaphore(self.parallel_requests)
        batch_timings:     List[float] = []
        cache_store_times: List[float] = []
        embedding_times:   List[float] = []
        total_cache_stored_count = 0

        async def process_batch(
            batch: List[DocstringRequest],
            batch_index: int,
            total: int,
            phase: str = "primary",
        ) -> Tuple[List[DocstringNode], List[DocstringRequest]]:
            """Make one LLM call, write results to cache+Neo4j immediately.
            Returns (docstrings_obtained, skipped_requests)."""
            nonlocal total_cache_stored_count
            async with semaphore:
                batch_start = time.time()
                logger.info(
                    f"[INFERENCE] {phase} batch {batch_index + 1}/{total} ({len(batch)} nodes)",
                    project_id=repo_id,
                    phase=phase,
                    batch_index=batch_index + 1,
                    total_batches=total,
                    batch_size=len(batch),
                )
                try:
                    response, prompt_input_tokens = await self.generate_response(
                        batch, repo_id
                    )
                    if not isinstance(response, DocstringResponse):
                        logger.warning(
                            f"[INFERENCE] Invalid response for {phase} batch "
                            f"{batch_index + 1}/{total}; treating all as skipped",
                            project_id=repo_id,
                        )
                        return [], list(batch)

                    returned_ids = {d.node_id for d in response.docstrings}
                    skipped      = [req for req in batch if req.node_id not in returned_ids]

                    # Generate embeddings for returned docstrings
                    emb_start = time.time()
                    docstring_embeddings: Dict[str, List[float]] = {}
                    for doc in response.docstrings:
                        docstring_embeddings[doc.node_id] = self.generate_embedding(
                            doc.docstring
                        )
                    embedding_times.append(time.time() - emb_start)

                    # Write to inference cache
                    cache_start       = time.time()
                    batch_cache_stored = 0
                    response_by_id    = {d.node_id: d for d in response.docstrings}
                    for request in batch:
                        doc = response_by_id.get(request.node_id)
                        if doc is None:
                            continue
                        metadata = request.metadata or {}
                        if (
                            cache_service
                            and metadata.get("should_cache")
                            and metadata.get("content_hash")
                        ):
                            try:
                                cache_service.store_inference(
                                    content_hash=metadata["content_hash"],
                                    inference_data={
                                        "node_id": doc.node_id,
                                        "docstring": doc.docstring,
                                        "tags": doc.tags,
                                    },
                                    project_id=repo_id,
                                    node_type=metadata.get("node_type"),
                                    content_length=len(request.text),
                                    embedding_vector=docstring_embeddings.get(doc.node_id),
                                    tags=doc.tags,
                                )
                                batch_cache_stored += 1
                                total_cache_stored_count += 1
                            except Exception as cache_err:
                                logger.warning(
                                    f"[INFERENCE] Cache store failed for node "
                                    f"{request.node_id}: {cache_err}",
                                    project_id=repo_id,
                                    node_id=request.node_id,
                                )
                    cache_time = time.time() - cache_start
                    cache_store_times.append(cache_time)

                    # Write to Neo4j (consolidate chunks first)
                    neo4j_start       = time.time()
                    processed_response = self.process_chunk_responses(response, batch)
                    if processed_response:
                        self.update_neo4j_with_docstrings(
                            repo_id, processed_response, docstring_embeddings
                        )
                    neo4j_time = time.time() - neo4j_start

                    elapsed = time.time() - batch_start
                    batch_timings.append(elapsed)
                    logger.info(
                        f"[INFERENCE] {phase} batch {batch_index + 1}/{total}: "
                        f"{len(response.docstrings)} returned, {len(skipped)} skipped, "
                        f"input_tokens={prompt_input_tokens}, "
                        f"emb={embedding_times[-1]:.2f}s, "
                        f"cache={cache_time:.3f}s ({batch_cache_stored} stored), "
                        f"neo4j={neo4j_time:.2f}s, total={elapsed:.2f}s",
                        project_id=repo_id,
                        phase=phase,
                        batch_index=batch_index + 1,
                        total_batches=total,
                        returned_count=len(response.docstrings),
                        skipped_count=len(skipped),
                        prompt_input_tokens=prompt_input_tokens,
                        embedding_time_seconds=embedding_times[-1],
                        cache_time_seconds=cache_time,
                        batch_cache_stored=batch_cache_stored,
                        neo4j_time_seconds=neo4j_time,
                        batch_total_seconds=elapsed,
                    )
                    return list(response.docstrings), skipped

                except Exception as exc:
                    elapsed = time.time() - batch_start
                    logger.error(
                        f"[INFERENCE] {phase} batch {batch_index + 1}/{total} failed: "
                        f"{exc} ({elapsed:.2f}s)",
                        project_id=repo_id,
                        phase=phase,
                        batch_index=batch_index + 1,
                        batch_total_seconds=elapsed,
                    )
                    return [], list(batch)

        # ── Phase 1: Primary LLM pass (all batches in parallel) ─────────────────
        total_primary = len(batches)
        primary_results = await asyncio.gather(
            *[process_batch(b, i, total_primary, "primary") for i, b in enumerate(batches)]
        )
        all_skipped: List[DocstringRequest] = []
        for docs, skipped in primary_results:
            all_docstrings["docstrings"].extend(docs)
            all_skipped.extend(skipped)

        primary_returned = sum(len(r[0]) for r in primary_results)
        logger.info(
            f"[INFERENCE] Primary pass complete: {total_primary} batches, "
            f"{primary_returned} docstrings returned, {len(all_skipped)} skipped",
            project_id=repo_id,
            primary_batches=total_primary,
            primary_returned=primary_returned,
            primary_skipped=len(all_skipped),
        )

        # ── Phase 2: Retry pass(es) on globally-collected skipped nodes ──────────
        try:
            max_retry_attempts = max(
                1, int(os.environ.get("INFERENCE_SKIP_RETRY_MAX_ATTEMPTS", "1"))
            )
        except (TypeError, ValueError):
            max_retry_attempts = 1

        for attempt in range(max_retry_attempts):
            if not all_skipped:
                break
            logger.info(
                f"[INFERENCE] Retry attempt {attempt + 1}/{max_retry_attempts}: "
                f"{len(all_skipped)} nodes to retry",
                project_id=repo_id,
                retry_attempt=attempt + 1,
                retry_max_attempts=max_retry_attempts,
                retry_node_count=len(all_skipped),
            )
            retry_batches = self._build_batches(all_skipped, project_id=repo_id)
            total_retry   = len(retry_batches)
            retry_results = await asyncio.gather(
                *[
                    process_batch(b, i, total_retry, f"retry-{attempt + 1}")
                    for i, b in enumerate(retry_batches)
                ]
            )
            newly_skipped: List[DocstringRequest] = []
            for docs, skipped in retry_results:
                all_docstrings["docstrings"].extend(docs)
                newly_skipped.extend(skipped)
            recovered = len(all_skipped) - len(newly_skipped)
            logger.info(
                f"[INFERENCE] Retry attempt {attempt + 1}: recovered {recovered}/"
                f"{len(all_skipped)}, still missing {len(newly_skipped)}",
                project_id=repo_id,
                retry_attempt=attempt + 1,
                retry_recovered=recovered,
                retry_still_missing=len(newly_skipped),
            )
            all_skipped = newly_skipped

        # ── Phase 3: Fallback stubs for anything still missing ───────────────────
        if all_skipped:
            logger.info(
                f"[INFERENCE] Writing fallback stubs for {len(all_skipped)} nodes "
                f"not recovered after {max_retry_attempts} retry attempt(s)",
                project_id=repo_id,
                fallback_count=len(all_skipped),
            )
            self._write_fallback_docstrings(repo_id, all_skipped)

        llm_batch_time   = time.time() - llm_batch_start
        avg_batch_time   = sum(batch_timings) / len(batch_timings)   if batch_timings   else 0.0
        avg_cache_time   = sum(cache_store_times) / len(cache_store_times) if cache_store_times else 0.0
        avg_emb_time     = sum(embedding_times)  / len(embedding_times)   if embedding_times   else 0.0

        logger.info(
            f"[INFERENCE] Completed LLM batch processing: "
            f"{total_primary} primary + {max_retry_attempts} retry pass(es) "
            f"in {llm_batch_time:.2f}s wall, "
            f"avg batch wall={avg_batch_time:.2f}s, "
            f"avg embedding={avg_emb_time:.2f}s, "
            f"avg cache={avg_cache_time*1000:.1f}ms, "
            f"cached {total_cache_stored_count} results",
            project_id=repo_id,
            primary_batches=total_primary,
            max_retry_attempts=max_retry_attempts,
            llm_batch_wall_seconds=llm_batch_time,
            avg_batch_wall_seconds=avg_batch_time,
            avg_embedding_seconds=avg_emb_time,
            avg_cache_store_ms=avg_cache_time * 1000,
            total_cache_stored_count=total_cache_stored_count,
        )

        updated_docstrings = all_docstrings

        # Update cache stats with storage info
        cache_stats["cache_stored"] = total_cache_stored_count
        cache_stats["cached_nodes_processed"] = len(cached_nodes)

        total_inference_time = time.time() - inference_start_time

        logger.info(
            f"[INFERENCE] Docstring generation completed in {total_inference_time:.2f}s: "
            f"Fetch: {fetch_time:.2f}s, "
            f"Search index: {search_index_time:.2f}s, "
            f"Cache lookup: {cache_lookup_time:.2f}s, "
            f"Batching: {batch_time:.2f}s, "
            f"Cached processing: {cached_process_time:.2f}s, "
            f"LLM batches: {llm_batch_time:.2f}s",
            project_id=repo_id,
            total_inference_time_seconds=total_inference_time,
            fetch_time_seconds=fetch_time,
            search_index_time_seconds=search_index_time,
            cache_lookup_time_seconds=cache_lookup_time,
            batch_time_seconds=batch_time,
            cached_process_time_seconds=cached_process_time,
            llm_batch_time_seconds=llm_batch_time,
        )

        return updated_docstrings, cache_stats

    async def generate_response(
        self, batch: List[DocstringRequest], repo_id: str
    ) -> Tuple[DocstringResponse, int]:
        # Prepare the code snippets
        code_snippets = ""
        for request in batch:
            code_snippets += (
                f"node_id: {request.node_id} \n```\n{request.text}\n```\n\n "
            )

        system_message = DOCSTRING_INFERENCE_SYSTEM_MESSAGE
        user_content = DOCSTRING_INFERENCE_USER_PROMPT_TEMPLATE.format(
            code_snippets=code_snippets
        )

        # Check total token count before sending — use provider-aware context window
        MAX_CONTEXT_TOKENS = self._get_inference_max_tokens()
        model = INFERENCE_TOKEN_COUNT_MODEL

        system_tokens = self.num_tokens_from_string(system_message, model)
        user_tokens = self.num_tokens_from_string(user_content, model)
        total_tokens = system_tokens + user_tokens

        if total_tokens > MAX_CONTEXT_TOKENS:
            # _build_batches should prevent this, but log a warning if it ever occurs.
            logger.warning(
                f"Batch exceeds token limit: {total_tokens} > {MAX_CONTEXT_TOKENS}. "
                f"Batch size: {len(batch)} nodes. Proceeding anyway (over-budget)."
            )

        messages = [
            {
                "role": "system",
                "content": system_message,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]

        logger.info(
            f"Parsing project {repo_id}: Starting the inference process... "
            f"(batch size: {len(batch)} nodes, total tokens: {total_tokens})"
        )

        try:
            result = await self.provider_service.call_llm_with_structured_output(
                messages=messages,
                output_schema=DocstringResponse,
                config_type="inference",
            )
        except Exception as e:
            logger.error(
                f"Parsing project {repo_id}: Inference request failed. Error: {str(e)}"
            )
            result = DocstringResponse(docstrings=[])

        logger.info(f"Parsing project {repo_id}: Inference request completed.")
        self._log_inference_output_calibration(batch, result, repo_id)
        return result, total_tokens

    def _write_fallback_docstrings(self, repo_id: str, skipped_requests) -> None:
        """Write minimal fallback docstrings for nodes the LLM skipped (e.g. short stubs)."""

        fallback_docstrings = []
        for req in skipped_requests:
            first_line = (req.text or "").strip().splitlines()[0] if req.text else ""
            docstring = f"Code stub: {first_line}" if first_line else "Code stub."
            fallback_docstrings.append(
                DocstringNode(node_id=req.node_id, docstring=docstring, tags=["UTILITY"])
            )

        if fallback_docstrings:
            self.update_neo4j_with_docstrings(
                repo_id, DocstringResponse(docstrings=fallback_docstrings)
            )

    def generate_embedding(self, text: str) -> List[float]:
        embedding = self.embedding_model.encode(text)
        return embedding.tolist()

    def batch_update_neo4j_with_cached_inference(
        self, nodes: List[Dict[str, Any]], repo_id: str
    ) -> int:
        """
        Batch update Neo4j with cached inference data for multiple nodes.
        Much faster than updating one node at a time.

        Returns the number of nodes updated.
        """
        if not nodes:
            return 0

        # Get project info ONCE for all nodes
        try:
            project = self.project_manager.get_project_from_db_by_id_sync(repo_id)
            repo_path = (
                project.get("repo_path")
                if project and isinstance(project, dict)
                else None
            )
        except Exception:
            repo_path = None
        is_local_repo = True if repo_path else False

        # Prepare batch data - reuse cached embeddings where available
        batch_data = []
        embeddings_generated = 0
        embeddings_reused = 0

        for node in nodes:
            cached_inference = node.get("cached_inference", {})
            if not cached_inference:
                continue

            docstring = cached_inference.get("docstring", "")
            tags = cached_inference.get("tags", [])

            # Reuse cached embedding if available, otherwise generate new one
            embedding = cached_inference.get("embedding_vector")
            if embedding is None:
                embedding = self.generate_embedding(docstring)
                embeddings_generated += 1
            else:
                embeddings_reused += 1

            batch_data.append(
                {
                    "node_id": node["node_id"],
                    "docstring": docstring,
                    "embedding": embedding,
                    "tags": tags,
                }
            )

        if not batch_data:
            return 0

        logger.debug(
            f"Batch updating {len(batch_data)} cached nodes "
            f"(embeddings: {embeddings_reused} reused, {embeddings_generated} generated)"
        )

        # Single Neo4j session for all updates
        with self.driver.session() as session:
            # Process in batches of 300 for optimal performance
            batch_size = 300
            for i in range(0, len(batch_data), batch_size):
                batch = batch_data[i : i + batch_size]
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (n:NODE {repoId: $repo_id, node_id: item.node_id})
                    SET n.docstring = item.docstring,
                        n.embedding = item.embedding,
                        n.tags = item.tags
                    """
                    + ("" if is_local_repo else ", n.text = null, n.signature = null"),
                    batch=batch,
                    repo_id=repo_id,
                )

        logger.info(
            f"Batch updated {len(batch_data)} cached nodes in Neo4j "
            f"(embeddings: {embeddings_reused} reused, {embeddings_generated} generated)"
        )
        return len(batch_data)

    async def update_neo4j_with_cached_inference(self, node: Dict[str, Any]) -> None:
        """Update Neo4j with cached inference data for a single node (legacy, use batch version)"""
        cached_inference = node.get("cached_inference", {})
        if not cached_inference:
            return

        # Extract inference data
        docstring = cached_inference.get("docstring", "")
        tags = cached_inference.get("tags", [])

        # Reuse cached embedding if available, otherwise generate new one
        embedding = cached_inference.get("embedding_vector")
        if embedding is None:
            logger.debug(
                f"Generating new embedding for cached inference node {node.get('node_id', 'unknown')}"
            )
            embedding = self.generate_embedding(docstring)
        else:
            logger.debug(
                f"Reusing cached embedding for node {node.get('node_id', 'unknown')}"
            )

        with self.driver.session() as session:
            project = self.project_manager.get_project_from_db_by_id_sync(
                node.get("project_id", "")
            )
            repo_path = project.get("repo_path") if project else None
            is_local_repo = True if repo_path else False

            session.run(
                """
                MATCH (n:NODE {repoId: $repo_id, node_id: $node_id})
                SET n.docstring = $docstring,
                    n.embedding = $embedding,
                    n.tags = $tags
                """
                + ("" if is_local_repo else ", n.text = null, n.signature = null"),
                repo_id=node.get("project_id", ""),
                node_id=node["node_id"],
                docstring=docstring,
                embedding=embedding,
                tags=tags,
            )

        logger.debug(f"Updated Neo4j with cached inference for node {node['node_id']}")

    def update_neo4j_with_docstrings(
        self,
        repo_id: str,
        docstrings: DocstringResponse,
        precomputed_embeddings: Optional[Dict[str, List[float]]] = None,
    ):
        """
        Update Neo4j with docstrings and embeddings.

        Args:
            repo_id: Project/repo ID
            docstrings: DocstringResponse with results
            precomputed_embeddings: Optional dict of node_id -> embedding to avoid regenerating
        """
        with self.driver.session() as session:
            batch_size = 300
            precomputed = precomputed_embeddings or {}
            docstring_list = [
                {
                    "node_id": n.node_id,
                    "docstring": n.docstring,
                    "tags": n.tags,
                    # Reuse precomputed embedding if available, otherwise generate
                    "embedding": precomputed.get(n.node_id)
                    or self.generate_embedding(n.docstring),
                }
                for n in docstrings.docstrings
            ]
            project = self.project_manager.get_project_from_db_by_id_sync(repo_id)
            repo_path = project.get("repo_path")
            is_local_repo = True if repo_path else False
            for i in range(0, len(docstring_list), batch_size):
                batch = docstring_list[i : i + batch_size]
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (n:NODE {repoId: $repo_id, node_id: item.node_id})
                    SET n.docstring = item.docstring,
                        n.embedding = item.embedding,
                        n.tags = item.tags
                    """
                    + ("" if is_local_repo else "REMOVE n.text, n.signature"),
                    batch=batch,
                    repo_id=repo_id,
                )

    def create_vector_index(self):
        with self.driver.session() as session:
            session.run(
                """
                CREATE VECTOR INDEX docstring_embedding IF NOT EXISTS
                FOR (n:NODE)
                ON (n.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 384,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            )

    async def run_inference(self, repo_id: str):
        run_inference_start = time.time()
        logger.info(
            f"[INFERENCE RUN] Starting inference pipeline for project {repo_id}",
            project_id=repo_id,
        )

        try:
            # Set status to INFERRING at the beginning (repo_id may be str or int)
            try:
                project_id_for_status = (
                    int(repo_id) if isinstance(repo_id, str) else repo_id
                )
            except (TypeError, ValueError):
                project_id_for_status = repo_id
            await self.project_manager.update_project_status(
                project_id_for_status, ProjectStatusEnum.INFERRING
            )

            # Generate docstrings
            docstrings, cache_stats = await self.generate_docstrings(repo_id)
            docstring_count = (
                len(docstrings.get("docstrings", []))
                if isinstance(docstrings, dict)
                else 0
            )
            logger.info(
                f"[INFERENCE RUN] Generated {docstring_count} docstrings",
                project_id=repo_id,
                docstring_count=docstring_count,
            )
            self.log_graph_stats(repo_id)

            # Create vector index
            vector_index_start = time.time()
            logger.info(
                f"[INFERENCE RUN] Creating vector index",
                project_id=repo_id,
            )
            self.create_vector_index()
            vector_index_time = time.time() - vector_index_start
            logger.info(
                f"[INFERENCE RUN] Created vector index in {vector_index_time:.2f}s",
                project_id=repo_id,
                vector_index_time_seconds=vector_index_time,
            )

            # Set status to READY after successful completion
            await self.project_manager.update_project_status(
                project_id_for_status, ProjectStatusEnum.READY
            )

            total_run_time = time.time() - run_inference_start
            logger.info(
                f"[INFERENCE RUN] Inference pipeline completed in {total_run_time:.2f}s",
                project_id=repo_id,
                total_run_time_seconds=total_run_time,
            )

            return cache_stats
        except Exception as e:
            logger.error(f"Inference failed for project {repo_id}: {e}")
            # Set status to ERROR on failure
            try:
                pid = int(repo_id) if isinstance(repo_id, str) else repo_id
                await self.project_manager.update_project_status(
                    pid, ProjectStatusEnum.ERROR
                )
            except Exception:
                pass
            raise

    def query_vector_index(
        self,
        project_id: str,
        query: str,
        node_ids: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict]:
        """
        Query the vector index for similar nodes.

        Note: This may fail if called during INFERRING status when embeddings/index
        are not yet ready. The calling tool (ask_knowledge_graph_queries) handles
        these errors gracefully by returning empty results.
        """
        embedding = self.generate_embedding(query)

        with self.driver.session() as session:
            try:
                if node_ids:
                    # Fetch context node IDs
                    result_neighbors = session.run(
                        """
                        MATCH (n:NODE)
                        WHERE n.repoId = $project_id AND n.node_id IN $node_ids
                        CALL {
                            WITH n
                            MATCH (n)-[*1..4]-(neighbor:NODE)
                            RETURN COLLECT(DISTINCT neighbor.node_id) AS neighbor_ids
                        }
                        RETURN COLLECT(DISTINCT n.node_id) + REDUCE(acc = [], neighbor_ids IN COLLECT(neighbor_ids) | acc + neighbor_ids) AS context_node_ids
                        """,
                        project_id=project_id,
                        node_ids=node_ids,
                    )
                    context_node_ids = result_neighbors.single()["context_node_ids"]

                    # Use vector index and filter by context_node_ids
                    result = session.run(
                        """
                        CALL db.index.vector.queryNodes('docstring_embedding', $initial_k, $embedding)
                        YIELD node, score
                        WHERE node.repoId = $project_id AND node.node_id IN $context_node_ids
                        RETURN node.node_id AS node_id,
                            node.docstring AS docstring,
                            node.file_path AS file_path,
                            node.start_line AS start_line,
                            node.end_line AS end_line,
                            node.name AS name,
                            node.type AS type,
                            score AS similarity
                        ORDER BY similarity DESC
                        LIMIT $top_k
                        """,
                        project_id=project_id,
                        embedding=embedding,
                        context_node_ids=context_node_ids,
                        initial_k=top_k * 10,  # Adjust as needed
                        top_k=top_k,
                    )
                else:
                    result = session.run(
                        """
                        CALL db.index.vector.queryNodes('docstring_embedding', $top_k, $embedding)
                        YIELD node, score
                        WHERE node.repoId = $project_id
                        RETURN node.node_id AS node_id,
                            node.docstring AS docstring,
                            node.file_path AS file_path,
                            node.start_line AS start_line,
                            node.end_line AS end_line,
                            node.name AS name,
                            node.type AS type,
                            score AS similarity
                        """,
                        project_id=project_id,
                        embedding=embedding,
                        top_k=top_k,
                    )

                # Ensure all fields are included in the final output
                return [dict(record) for record in result]
            except Exception as e:
                logger.warning(
                    f"Error querying vector index for project {project_id}: {e}"
                )
                return []
