import math
import os
import subprocess
import tempfile
import warnings
from collections import Counter, defaultdict, namedtuple
from pathlib import Path

import networkx as nx
from grep_ast import TreeContext, filename_to_lang
from pygments.lexers import guess_lexer_for_filename
from pygments.token import Token
from pygments.util import ClassNotFound
from tqdm import tqdm
from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from app.core.database import get_db
from app.modules.parsing.graph_construction.parsing_helper import (  # noqa: E402
    ParseHelper,
)
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Optional SCIP integration for precise Python symbol resolution
try:
    import sys as _sys
    _SCIP_DIR = str(Path(__file__).resolve().parents[4] / "scip")
    if _SCIP_DIR not in _sys.path:
        _sys.path.insert(0, _SCIP_DIR)
    from read_scip import (  # noqa: E402
        load_index as scip_load_index,
        build_document_records as scip_build_document_records,
        symbol_kind as scip_symbol_kind,
        short_name as scip_short_name,
    )
    _SCIP_AVAILABLE = True
except (
    ImportError,
    ModuleNotFoundError,
    RuntimeError,
    FileNotFoundError,
    OSError,
    IOError,
    Exception,  # catch-all for any other unexpected import-time errors
) as _exc:
    logger.info("SCIP integration unavailable (missing module): %s", _exc)
    _SCIP_AVAILABLE = False

# tree_sitter is throwing a FutureWarning
warnings.simplefilter("ignore", category=FutureWarning)
Tag = namedtuple("Tag", "rel_fname fname line end_line name ident kind type text".split())

# SCIP symbol-kind → Tag type mapping (used by _scip_tags_from_document)
_SCIP_KIND_TO_TAG_TYPE = {
    "method": "method",
    "class": "class",
    "variable": "variable",
    "module": "module",
}

# Tag type → node-type string used by find_node_by_range for text extraction
_TAG_TYPE_TO_NODE_TYPE = {
    "method": "FUNCTION",
    "function": "FUNCTION",
    "class": "CLASS",
    "interface": "INTERFACE",
}


class RepoMap:
    # Parsing logic adapted from aider (https://github.com/paul-gauthier/aider)
    # Modified and customized for potpie's parsing needs with detailed tags, relationship tracking etc

    def __init__(
        self,
        map_tokens=1024,
        root=None,
        main_model=None,
        io=None,
        repo_content_prefix=None,
        verbose=False,
        max_context_window=None,
        map_mul_no_files=8,
    ):
        self.io = io
        self.verbose = verbose

        if not root:
            root = os.getcwd()
        self.root = root

        self.max_map_tokens = map_tokens
        self.map_mul_no_files = map_mul_no_files
        self.max_context_window = max_context_window

        self.repo_content_prefix = repo_content_prefix
        self.parse_helper = ParseHelper(next(get_db()))
        self.scip_docs = {}  # populated by _run_scip_indexing for Python files
        self._scip_repo_dir = None   # repo_dir that self.scip_docs corresponds to
        self._scip_repo_mtime = None # newest .py mtime when index was built

    def get_repo_map(
        self, chat_files, other_files, mentioned_fnames=None, mentioned_idents=None
    ):
        if self.max_map_tokens <= 0:
            return
        if not other_files:
            return
        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        max_map_tokens = self.max_map_tokens

        # With no files in the chat, give a bigger view of the entire repo
        padding = 4096
        if max_map_tokens and self.max_context_window:
            target = min(
                max_map_tokens * self.map_mul_no_files,
                self.max_context_window - padding,
            )
        else:
            target = 0
        if not chat_files and self.max_context_window and target > 0:
            max_map_tokens = target

        try:
            files_listing = self.get_ranked_tags_map(
                chat_files,
                other_files,
                max_map_tokens,
                mentioned_fnames,
                mentioned_idents,
            )
        except RecursionError:
            self.io.tool_error("Disabling repo map, git repo too large?")
            self.max_map_tokens = 0
            return

        if not files_listing:
            return

        num_tokens = self.token_count(files_listing)
        if self.verbose:
            self.io.tool_output(f"Repo-map: {num_tokens / 1024:.1f} k-tokens")

        if chat_files:
            other = "other "
        else:
            other = ""

        if self.repo_content_prefix:
            repo_content = self.repo_content_prefix.format(other=other)
        else:
            repo_content = ""

        repo_content += files_listing

        return repo_content

    def get_rel_fname(self, fname):
        return os.path.relpath(fname, self.root)

    def split_path(self, path):
        path = os.path.relpath(path, self.root)
        return [path + ":"]

    def save_tags_cache(self):
        pass

    def get_mtime(self, fname):
        try:
            return os.path.getmtime(fname)
        except FileNotFoundError:
            self.io.tool_error(f"File not found error: {fname}")

    def get_tags(self, fname, rel_fname):
        # Check if the file is in the cache and if the modification time has not changed
        file_mtime = self.get_mtime(fname)
        if file_mtime is None:
            return []

        if _SCIP_AVAILABLE:
            # Use SCIP-derived tags for Python files when available
            if fname.endswith(".py") and self.scip_docs:
                if rel_fname not in self.scip_docs:
                    logger.warning(f"SCIP document record missing for {rel_fname}")
                    return []
                return list(self._scip_tags_from_document(
                    self.scip_docs[rel_fname], fname, rel_fname
                ))

        data = list(self.get_tags_raw(fname, rel_fname))

        return data

    def _scip_tags_from_document(self, doc_record, fname, rel_fname):
        """Yield Tag namedtuples from a SCIP DocumentRecord.

        Maps SCIP fully-qualified symbols to the same Tag format that
        tree-sitter get_tags_raw produces.  ``tag.name`` stays as the
        short identifier (for display / node naming), while ``tag.ident``
        carries the full SCIP symbol so that def-ref matching in
        create_graph is compiler-accurate with zero false positives.

        ``tag.line`` and ``tag.end_line`` come from the SCIP occurrence's
        ``range`` (start) and ``enclosing_range`` (end).  Node text is
        read directly from ``file_lines[line:end_line+1]``.
        """
        # Read file for text extraction
        code = self.io.read_text(fname) or ""
        file_lines = code.splitlines()

        for defn in doc_record.definitions:
            kind = scip_symbol_kind(defn.symbol)
            if kind == "parameter":
                continue
            tag_type = _SCIP_KIND_TO_TAG_TYPE.get(kind, "unknown")

            # Resolve full source text for this definition
            node_text = ""
            end_line = defn.end_line if defn.end_line >= 0 else defn.line

            if end_line >= defn.line and defn.line >= 0:
                # enclosing_range gave us a multi-line extent — slice directly
                node_text = "\n".join(file_lines[defn.line : end_line + 1])
            else:
                logger.error(
                    "SCIP definition missing multi-line enclosing_range: "
                    "symbol=%s line=%d end_line=%d file=%s",
                    defn.symbol, defn.line, end_line, rel_fname,
                )

            yield Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=scip_short_name(defn.symbol),
                ident=defn.symbol,
                kind="def",
                line=defn.line,
                end_line=end_line,
                type=tag_type,
                text=node_text,
            )

        for ref in doc_record.references:
            kind = scip_symbol_kind(ref.symbol)
            if kind == "parameter":
                continue
            tag_type = _SCIP_KIND_TO_TAG_TYPE.get(kind, "unknown")
            yield Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=scip_short_name(ref.symbol),
                ident=ref.symbol,
                kind="ref",
                line=ref.line,
                end_line=ref.end_line if ref.end_line >= 0 else ref.line,
                type=tag_type,
                text="",
            )

    def get_tags_raw(self, fname, rel_fname):
        lang = filename_to_lang(fname)
        if not lang:
            return

        language = get_language(lang)
        parser = get_parser(lang)

        query_scm = get_scm_fname(lang)
        if not query_scm.exists():
            return
        query_scm = query_scm.read_text()

        code = self.io.read_text(fname)
        if not code:
            return
        tree = parser.parse(bytes(code, "utf-8"))
        file_lines = code.splitlines()

        # Run the tags queries
        try:
            query = Query(language, query_scm)
            cursor = QueryCursor(query)
        except Exception as e:
            logger.warning(f"Failed to create query for {fname}: {e}")
            return

        captures = []
        try:
            for _, capture_dict in cursor.matches(tree.root_node):
                for capture_name, nodes in capture_dict.items():
                    for node in nodes:
                        captures.append((node, capture_name))
        except Exception as e:
            logger.warning(f"Failed to execute query matches for {fname}: {e}")
            return

        saw = set()

        for node, tag in captures:
            node_text = node.text.decode("utf-8")

            if tag.startswith("name.definition."):
                kind = "def"
                type = tag.split(".")[-1]

            elif tag.startswith("name.reference."):
                kind = "ref"
                type = tag.split(".")[-1]

            else:
                continue

            saw.add(kind)

            # Enhanced node text extraction for Java methods
            if lang == "java" and type == "method":
                # Handle method calls with object references (e.g., productService.listAllProducts())
                parent = node.parent
                if parent and parent.type == "method_invocation":
                    object_node = parent.child_by_field_name("object")
                    if object_node:
                        node_text = f"{object_node.text.decode('utf-8')}.{node_text}"

            # Extract full source text for definition tags
            text = ""
            tag_end_line = node.end_point[0]
            if kind == "def":
                ts_node_type = _TAG_TYPE_TO_NODE_TYPE.get(type)
                if ts_node_type:
                    ts_node = RepoMap.find_node_by_range(
                        tree.root_node, node.start_point[0], ts_node_type
                    )
                    actual_end = (
                        ts_node.end_point[0] if ts_node else node.start_point[0]
                    )
                    tag_end_line = actual_end
                    text = "\n".join(
                        file_lines[node.start_point[0] : actual_end + 1]
                    )

            result = Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=node_text,
                ident=node_text,
                kind=kind,
                line=node.start_point[0],
                end_line=tag_end_line,
                type=type,
                text=text,
            )

            yield result

        if "ref" in saw:
            return
        if "def" not in saw:
            return

        try:
            lexer = guess_lexer_for_filename(fname, code)
        except ClassNotFound:
            return

        tokens = list(lexer.get_tokens(code))
        tokens = [token[1] for token in tokens if token[0] in Token.Name]

        for token in tokens:
            yield Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=token,
                ident=token,
                kind="ref",
                line=-1,
                end_line=-1,
                type="unknown",
                text="",
            )

    @staticmethod
    def get_tags_from_code(fname, code):
        lang = filename_to_lang(fname)
        if not lang:
            return

        language = get_language(lang)
        parser = get_parser(lang)

        query_scm = get_scm_fname(lang)
        if not query_scm.exists():
            return
        query_scm = query_scm.read_text()

        if not code:
            return
        tree = parser.parse(bytes(code, "utf-8"))
        file_lines = code.splitlines()

        # Run the tags queries
        try:
            query = Query(language, query_scm)
            cursor = QueryCursor(query)
        except Exception as e:
            logger.warning(f"Failed to create query for {fname}: {e}")
            return

        captures = []
        try:
            for _, capture_dict in cursor.matches(tree.root_node):
                for capture_name, nodes in capture_dict.items():
                    for node in nodes:
                        captures.append((node, capture_name))
        except Exception as e:
            logger.warning(f"Failed to execute query matches for {fname}: {e}")
            return

        saw = set()
        for node, tag in captures:
            if tag.startswith("name.definition."):
                kind = "def"
                type = tag.split(".")[-1]  #
            elif tag.startswith("name.reference."):
                kind = "ref"
                type = tag.split(".")[-1]  #
            else:
                continue

            saw.add(kind)

            node_text = node.text.decode("utf-8")

            # Extract full source text for definition tags
            text = ""
            tag_end_line = node.end_point[0]
            if kind == "def":
                ts_node_type = _TAG_TYPE_TO_NODE_TYPE.get(type)
                if ts_node_type:
                    ts_node = RepoMap.find_node_by_range(
                        tree.root_node, node.start_point[0], ts_node_type
                    )
                    actual_end = (
                        ts_node.end_point[0] if ts_node else node.start_point[0]
                    )
                    tag_end_line = actual_end
                    text = "\n".join(
                        file_lines[node.start_point[0] : actual_end + 1]
                    )

            result = Tag(
                rel_fname=fname,
                fname=fname,
                name=node_text,
                ident=node_text,
                kind=kind,
                line=node.start_point[0],
                end_line=tag_end_line,
                type=type,
                text=text,
            )

            yield result

        if "ref" in saw:
            return
        if "def" not in saw:
            return

        # We saw defs, without any refs
        # Some tags files only provide defs (cpp, for example)
        # Use pygments to backfill refs

        try:
            lexer = guess_lexer_for_filename(fname, code)
        except ClassNotFound:
            return

        tokens = list(lexer.get_tokens(code))
        tokens = [token[1] for token in tokens if token[0] in Token.Name]

        for token in tokens:
            yield Tag(
                rel_fname=fname,
                fname=fname,
                name=token,
                ident=token,
                kind="ref",
                line=-1,
                end_line=-1,
                type="unknown",
                text="",
            )

    def get_ranked_tags(
        self, chat_fnames, other_fnames, mentioned_fnames, mentioned_idents
    ):
        defines = defaultdict(set)
        references = defaultdict(list)
        definitions = defaultdict(set)

        personalization = dict()

        fnames = set(chat_fnames).union(set(other_fnames))
        chat_rel_fnames = set()

        fnames = sorted(fnames)

        # Default personalization for unspecified files is 1/num_nodes
        # https://networkx.org/documentation/stable/_modules/networkx/algorithms/link_analysis/pagerank_alg.html#pagerank
        personalize = 100 / len(fnames)

        fnames = tqdm(fnames)

        for fname in fnames:
            if not Path(fname).is_file():
                if fname not in self.warned_files:
                    if Path(fname).exists():
                        self.io.tool_error(
                            f"Repo-map can't include {fname}, it is not a normal file"
                        )
                    else:
                        self.io.tool_error(
                            f"Repo-map can't include {fname}, it no longer exists"
                        )

                self.warned_files.add(fname)
                continue

            # dump(fname)
            rel_fname = self.get_rel_fname(fname)

            if fname in chat_fnames:
                personalization[rel_fname] = personalize
                chat_rel_fnames.add(rel_fname)

            if rel_fname in mentioned_fnames:
                personalization[rel_fname] = personalize

            tags = list(self.get_tags(fname, rel_fname))
            if tags is None:
                continue

            for tag in tags:
                if tag.kind == "def":
                    defines[tag.ident].add(rel_fname)
                    key = (rel_fname, tag.ident)
                    definitions[key].add(tag)

                if tag.kind == "ref":
                    references[tag.ident].append(rel_fname)

        ##
        # dump(defines)
        # dump(references)
        # dump(personalization)

        if not references:
            references = dict((k, list(v)) for k, v in defines.items())

        # Build a reverse lookup so that short mentioned_idents (e.g.
        # "run") can boost full SCIP symbol keys that contain them.
        # For tree-sitter tags ident == name, so the lookup is identity.
        ident_to_short: dict[str, str] = {}
        for ident_key in set(defines.keys()) | set(references.keys()):
            # For SCIP symbols the short name is tag.name, but we only
            # have the ident key here.  We can derive the short form by
            # checking whether any mentioned_ident is a substring.
            for mi in mentioned_idents:
                if mi in ident_key:
                    ident_to_short[ident_key] = mi
                    break

        idents = set(defines.keys()).intersection(set(references.keys()))

        G = nx.MultiDiGraph()

        for ident in idents:
            definers = defines[ident]
            short = ident_to_short.get(ident)
            if short and short in mentioned_idents:
                mul = 10
            elif ident.startswith("_"):
                mul = 0.1
            else:
                mul = 1

            for referencer, num_refs in Counter(references[ident]).items():
                for definer in definers:
                    # dump(referencer, definer, num_refs, mul)
                    # if referencer == definer:
                    #    continue

                    # scale down so high freq (low value) mentions don't dominate
                    num_refs = math.sqrt(num_refs)

                    G.add_edge(referencer, definer, weight=mul * num_refs, ident=ident)

        if not references:
            pass

        if personalization:
            pers_args = dict(personalization=personalization, dangling=personalization)
        else:
            pers_args = dict()

        try:
            ranked = nx.pagerank(G, weight="weight", **pers_args)
        except ZeroDivisionError:
            return []

        # distribute the rank from each source node, across all of its out edges
        ranked_definitions = defaultdict(float)
        for src in G.nodes:
            src_rank = ranked[src]
            total_weight = sum(
                data["weight"] for _src, _dst, data in G.out_edges(src, data=True)
            )
            # dump(src, src_rank, total_weight)
            for _src, dst, data in G.out_edges(src, data=True):
                data["rank"] = src_rank * data["weight"] / total_weight
                ident = data["ident"]
                ranked_definitions[(dst, ident)] += data["rank"]

        ranked_tags = []
        ranked_definitions = sorted(
            ranked_definitions.items(), reverse=True, key=lambda x: x[1]
        )

        # dump(ranked_definitions)

        for (fname, ident), rank in ranked_definitions:
            if fname in chat_rel_fnames:
                continue
            ranked_tags += list(definitions.get((fname, ident), []))

        rel_other_fnames_without_tags = set(
            self.get_rel_fname(fname) for fname in other_fnames
        )

        fnames_already_included = set(rt[0] for rt in ranked_tags)

        top_rank = sorted(
            [(rank, node) for (node, rank) in ranked.items()], reverse=True
        )
        for rank, fname in top_rank:
            if fname in rel_other_fnames_without_tags:
                rel_other_fnames_without_tags.remove(fname)
            if fname not in fnames_already_included:
                ranked_tags.append((fname,))

        for fname in rel_other_fnames_without_tags:
            ranked_tags.append((fname,))

        return ranked_tags

    def get_ranked_tags_map(
        self,
        chat_fnames,
        other_fnames=None,
        max_map_tokens=None,
        mentioned_fnames=None,
        mentioned_idents=None,
    ):
        if not other_fnames:
            other_fnames = list()
        if not max_map_tokens:
            max_map_tokens = self.max_map_tokens
        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        ranked_tags = self.get_ranked_tags(
            chat_fnames, other_fnames, mentioned_fnames, mentioned_idents
        )

        num_tags = len(ranked_tags)
        lower_bound = 0
        upper_bound = num_tags
        best_tree = None
        best_tree_tokens = 0

        chat_rel_fnames = [self.get_rel_fname(fname) for fname in chat_fnames]

        # Guess a small starting number to help with giant repos
        middle = min(max_map_tokens // 25, num_tags)

        self.tree_cache = dict()

        while lower_bound <= upper_bound:
            tree = self.to_tree(ranked_tags[:middle], chat_rel_fnames)
            num_tokens = self.token_count(tree)

            if num_tokens < max_map_tokens and num_tokens > best_tree_tokens:
                best_tree = tree
                best_tree_tokens = num_tokens

            if num_tokens < max_map_tokens:
                lower_bound = middle + 1
            else:
                upper_bound = middle - 1

            middle = (lower_bound + upper_bound) // 2

        return best_tree

    tree_cache = dict()

    def render_tree(self, abs_fname, rel_fname, lois):
        key = (rel_fname, tuple(sorted(lois)))

        if key in self.tree_cache:
            return self.tree_cache[key]

        code = self.io.read_text(abs_fname) or ""
        if not code.endswith("\n"):
            code += "\n"

        context = TreeContext(
            rel_fname,
            code,
            color=False,
            line_number=False,
            child_context=False,
            last_line=False,
            margin=0,
            mark_lois=False,
            loi_pad=0,
            show_top_of_file_parent_scope=False,
        )

        for start, end in lois:
            context.add_lines_of_interest(range(start, end + 1))
        context.add_context()
        res = context.format()
        self.tree_cache[key] = res
        return res

    def create_relationship(
        G, source, target, relationship_type, seen_relationships, extra_data=None
    ):
        """Helper to create relationships with proper direction checking"""
        if source == target:
            return False

        # Determine correct direction based on node types
        source_data = G.nodes[source]
        target_data = G.nodes[target]

        # Prevent duplicate bidirectional relationships
        rel_key = (source, target, relationship_type)
        reverse_key = (target, source, relationship_type)

        if rel_key in seen_relationships or reverse_key in seen_relationships:
            return False

        # Only create relationship if we have right direction:
        # 1. Interface method implementations should point to interface declaration
        # 2. Method calls should point to method definitions
        # 3. Class references should point to class definitions
        valid_direction = False

        if relationship_type == "REFERENCES":
            # Implementation -> Interface
            if (
                source_data.get("type") == "FUNCTION"
                and target_data.get("type") == "FUNCTION"
                and "Impl" in source
            ):  # Implementation class
                valid_direction = True

            # Caller -> Callee
            elif source_data.get("type") == "FUNCTION":
                valid_direction = True

            # Class Usage -> Class Definition
            elif target_data.get("type") == "CLASS":
                valid_direction = True

        if valid_direction:
            G.add_edge(source, target, type=relationship_type, **(extra_data or {}))
            seen_relationships.add(rel_key)
            return True

        return False

    @staticmethod
    def _newest_py_mtime(repo_dir: str) -> float:
        """Return the newest mtime among .py files under repo_dir (0 if none)."""
        newest = 0.0
        for root, _dirs, files in os.walk(repo_dir):
            for f in files:
                if f.endswith(".py"):
                    try:
                        mt = os.path.getmtime(os.path.join(root, f))
                        if mt > newest:
                            newest = mt
                    except OSError:
                        pass
        return newest

    def _run_scip_indexing(self, repo_dir):
        """Run scip-python on repo_dir and populate self.scip_docs.

        Results are cached: if repo_dir and the newest .py mtime are
        unchanged since the last call the subprocess is skipped.

        If scip-python is not installed or indexing fails, self.scip_docs
        remains empty and get_tags falls back to tree-sitter.
        """
        if not _SCIP_AVAILABLE:
            logger.info("SCIP bindings not available, skipping Python SCIP indexing")
            return
        logger.info("Running SCIP indexing for Python files in repo_dir: %s", repo_dir)
        # ── cache check ──────────────────────────────────────────────
        current_mtime = self._newest_py_mtime(repo_dir)
        if (
            self._scip_repo_dir == repo_dir
            and self._scip_repo_mtime == current_mtime
            and self.scip_docs
        ):
            logger.debug("SCIP index cache hit — reusing previous results")
            return

        scip_output = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".scip", delete=False) as tmp:
                scip_output = tmp.name

            project_name = os.path.basename(repo_dir) or "project"
            logger.info(f"Running scip-python index on {repo_dir}, output to {scip_output}")
            result = subprocess.run(
                [
                    "scip-python", "index",
                    "--cwd", repo_dir,
                    "--project-name", project_name,
                    "--output", scip_output,
                ],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                # Keep timeout conservative; consider making configurable
                # for very large repos via an env var or constructor param.
                timeout=120,
            )

            if result.returncode == 0 and os.path.exists(scip_output):
                index = scip_load_index(scip_output)
                self.scip_docs = scip_build_document_records(index)
                self._scip_repo_dir = repo_dir
                self._scip_repo_mtime = current_mtime
                logger.info(
                    f"SCIP indexing completed: {len(self.scip_docs)} Python files indexed"
                )
                # scip-python may emit harmless warnings on stderr even on
                # success (e.g. unresolved third-party imports); log at
                # DEBUG to avoid noisy output.
                if result.stderr:
                    logger.debug(f"scip-python stderr: {result.stderr[:500]}")
            else:
                logger.warning(
                    f"scip-python failed (rc={result.returncode}): "
                    f"{result.stderr[:500]}"
                )
                self.scip_docs = {}

        except FileNotFoundError:
            logger.warning(
                "scip-python not found on PATH, "
                "falling back to tree-sitter for Python files"
            )
            self.scip_docs = {}
        except subprocess.TimeoutExpired:
            logger.warning(
                "scip-python timed out after 120s — repo may be too large. "
                "Falling back to tree-sitter for Python files"
            )
            self.scip_docs = {}
        except Exception as e:
            logger.warning(f"SCIP indexing failed: {e}, falling back to tree-sitter")
            self.scip_docs = {}
        finally:
            # Clean up temp file in all cases
            if scip_output and os.path.exists(scip_output):
                try:
                    os.unlink(scip_output)
                except OSError:
                    pass

    def create_graph(self, repo_dir):
        G = nx.MultiDiGraph()
        defines = defaultdict(set)
        references = defaultdict(set)
        seen_relationships = set()

        # Load combined ignore patterns (.gitignore + .potpieignore)
        from app.modules.code_provider.ignore_spec import load_ignore_spec
        _ignore_spec = load_ignore_spec(repo_dir)

        # Load .potpieallowedlang allowed-suffix whitelist
        _allowed_suffixes = None
        _potpieallowedlang_path = os.path.join(repo_dir, ".potpieallowedlang")
        if os.path.exists(_potpieallowedlang_path):
            try:
                with open(_potpieallowedlang_path, "r", encoding="utf-8") as _f:
                    # Each line is a glob like "*.py", "*.dml"; strip to just the suffix
                    _allowed_suffixes = set()
                    for _line in _f.read().splitlines():
                        _line = _line.strip()
                        if _line and not _line.startswith("#"):
                            # Accept both "*.py" and ".py" forms
                            suffix = _line.lstrip("*")
                            if suffix:
                                _allowed_suffixes.add(suffix)
                    if _allowed_suffixes:
                        logger.info(
                            "Loaded .potpieallowedlang whitelist: %s",
                            _allowed_suffixes,
                        )
                    else:
                        _allowed_suffixes = None
            except Exception:
                pass

        # Attempt SCIP indexing before the main walk; _run_scip_indexing
        # no-ops quickly if scip-python is unavailable or the repo has no
        # Python files (the index will simply contain zero documents).
        if _allowed_suffixes and ".py" in _allowed_suffixes:
            self._run_scip_indexing(repo_dir)

        for root, dirs, files in os.walk(repo_dir):
            # Get relative path from repo_dir to avoid skipping paths that contain .repos_local etc.
            try:
                rel_path = Path(root).relative_to(repo_dir)
                # Handle root directory (rel_path == '.') and convert to tuple
                rel_parts = rel_path.parts if rel_path != Path(".") else ()
            except ValueError:
                # If relative_to fails, skip this path (shouldn't happen in normal os.walk)
                continue

            # Skip .git directory (worktrees have .git as a file, not a directory)
            skip_this_dir = False
            if ".git" in rel_parts:
                # Find where .git appears in the relative path
                for i, part in enumerate(rel_parts):
                    if part == ".git":
                        # Check if this .git is a directory
                        git_path = Path(repo_dir) / Path(*rel_parts[: i + 1])
                        if git_path.is_dir():
                            # Skip this .git directory
                            skip_this_dir = True
                            break
                        # If it's a file, it's a worktree - continue processing
                        break

            if skip_this_dir:
                continue

            # Skip hidden directories except .github, .vscode, etc. that might contain code
            # Only check relative path parts, not the base path
            if any(
                part.startswith(".") and part not in [".github", ".vscode"]
                for part in rel_parts
            ):
                continue

            # Prune dirs in-place to skip ignored directories
            if _ignore_spec:
                dirs[:] = [
                    d for d in dirs
                    if not _ignore_spec.match_file(
                        os.path.relpath(os.path.join(root, d), repo_dir) + "/"
                    )
                ]

            for file in files:
                # Skip files whose suffix is not in the allowed-language whitelist
                if _allowed_suffixes:
                    file_suffix = os.path.splitext(file)[1]  # e.g. ".py"
                    if file_suffix not in _allowed_suffixes:
                        continue

                file_path = os.path.join(root, file)
                file_rel_path = os.path.relpath(file_path, repo_dir)

                # Skip files matching ignore patterns
                if _ignore_spec and _ignore_spec.match_file(file_rel_path):
                    continue

                if not self.parse_helper.is_text_file(file_path):
                    continue

                tags = self.get_tags(file_path, file_rel_path)
                if tags:
                    logger.info(f"\nProcessing file: {file_rel_path}")

                    # Add file node
                    file_node_name = file_rel_path
                    file_text = self.io.read_text(file_path) or ""
                    if not G.has_node(file_node_name):
                        G.add_node(
                            file_node_name,
                            file=file_rel_path,
                            type="FILE",
                            text=file_text,
                            line=0,
                            end_line=0,
                            name=file_rel_path.split("/")[-1],
                        )

                    current_class = None
                    current_method = None

                    # Process all tags in file
                    for tag in tags:
                        if tag.kind == "def":
                            if tag.type == "class":
                                node_type = "CLASS"
                                current_class = tag.name
                                current_method = None
                            elif tag.type == "interface":
                                node_type = "INTERFACE"
                                current_class = tag.name
                                current_method = None
                            elif tag.type in ["method", "function"]:
                                node_type = "FUNCTION"
                                current_method = tag.name
                            else:
                                continue

                            # Create fully qualified node name
                            if current_class:
                                node_name = f"{file_rel_path}:{current_class}.{tag.name}"
                            else:
                                node_name = f"{file_rel_path}:{tag.name}"

                            # Source text is pre-computed by get_tags_raw /
                            # _scip_tags_from_document and stored in tag.text
                            node_text = tag.text

                            # Add node
                            if not G.has_node(node_name):
                                G.add_node(
                                    node_name,
                                    file=file_rel_path,
                                    line=tag.line,
                                    end_line=tag.end_line,
                                    type=node_type,
                                    name=tag.name,
                                    class_name=current_class,
                                    text=node_text,
                                )

                                # Add CONTAINS relationship from file
                                rel_key = (file_node_name, node_name, "CONTAINS")
                                if rel_key not in seen_relationships:
                                    G.add_edge(
                                        file_node_name,
                                        node_name,
                                        type="CONTAINS",
                                        ident=tag.name,
                                    )
                                    seen_relationships.add(rel_key)

                            # Record definition — use tag.ident (full SCIP
                            # symbol for Python, short name for tree-sitter)
                            # so def→ref matching is compiler-accurate.
                            defines[tag.ident].add(node_name)

                        elif tag.kind == "ref":
                            # Handle references
                            if current_class and current_method:
                                source = f"{file_rel_path}:{current_class}.{current_method}"
                            elif current_method:
                                source = f"{file_rel_path}:{current_method}"
                            else:
                                source = file_rel_path

                            references[tag.ident].add(
                                (
                                    source,
                                    tag.line,
                                    tag.end_line,
                                    current_class,
                                    current_method,
                                )
                            )

        for ident, refs in references.items():
            target_nodes = defines.get(ident, set())

            for source, line, end_line, src_class, src_method in refs:
                for target in target_nodes:
                    if source == target:
                        continue

                    if G.has_node(source) and G.has_node(target):
                        RepoMap.create_relationship(
                            G,
                            source,
                            target,
                            "REFERENCES",
                            seen_relationships,
                            {
                                "ident": ident,
                                "ref_line": line,
                                "end_ref_line": end_line,
                            },
                        )

        return G

    @staticmethod
    def get_language_for_file(file_path):
        # Map file extensions to tree-sitter languages
        extension = os.path.splitext(file_path)[1].lower()
        language_map = {
            ".py": get_language("python"),
            ".js": get_language("javascript"),
            ".ts": get_language("typescript"),
            ".c": get_language("c"),
            ".cs": get_language("c_sharp"),
            ".cpp": get_language("cpp"),
            ".el": get_language("elisp"),
            ".ex": get_language("elixir"),
            ".exs": get_language("elixir"),
            ".elm": get_language("elm"),
            ".go": get_language("go"),
            ".java": get_language("java"),
            ".ml": get_language("ocaml"),
            ".mli": get_language("ocaml"),
            ".php": get_language("php"),
            ".ql": get_language("ql"),
            ".rb": get_language("ruby"),
            ".rs": get_language("rust"),
        }
        return language_map.get(extension)

    @staticmethod
    def find_node_by_range(root_node, start_line, node_type):
        def traverse(node):
            if node.start_point[0] <= start_line and node.end_point[0] >= start_line:
                if node_type == "FUNCTION" and node.type in [
                    "function_definition",
                    "method",
                    "method_declaration",
                    "function",
                ]:
                    return node
                elif node_type in ["CLASS", "INTERFACE"] and node.type in [
                    "class_definition",
                    "interface",
                    "class",
                    "class_declaration",
                    "interface_declaration",
                ]:
                    return node
                for child in node.children:
                    result = traverse(child)
                    if result:
                        return result
            return None

        return traverse(root_node)

    def to_tree(self, tags, chat_rel_fnames):
        if not tags:
            return ""

        tags = [tag for tag in tags if tag[0] not in chat_rel_fnames]
        # Sort by all fields except 'text' (last field) to avoid comparing large text strings
        tags = sorted(tags, key=lambda t: (t.rel_fname, t.line, t.kind, t.name))

        cur_fname = None
        cur_abs_fname = None
        lois = None
        output = ""

        # add a bogus tag at the end so we trip the this_fname != cur_fname...
        dummy_tag = (None,)
        for tag in tags + [dummy_tag]:
            this_rel_fname = tag[0]

            # ... here ... to output the final real entry in the list
            if this_rel_fname != cur_fname:
                if lois is not None:
                    output += "\n"
                    output += cur_fname + ":\n"
                    output += self.render_tree(cur_abs_fname, cur_fname, lois)
                    lois = None
                elif cur_fname:
                    output += "\n" + cur_fname + "\n"
                if type(tag) is Tag:
                    lois = []
                    cur_abs_fname = tag.fname
                cur_fname = this_rel_fname

            if lois is not None:
                lois.append((tag.line, tag.end_line))

        # truncate long lines, in case we get minified js or something else crazy
        output = "\n".join([line[:100] for line in output.splitlines()]) + "\n"

        return output


def get_scm_fname(lang):
    # Load the tags queries
    try:
        return Path(os.path.dirname(__file__)).joinpath(
            "queries", f"tree-sitter-{lang}-tags.scm"
        )
    except KeyError:
        return
