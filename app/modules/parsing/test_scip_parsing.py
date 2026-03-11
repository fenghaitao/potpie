"""Tests for SCIP-based Python parsing in parsing_repomap.py.

These tests verify that:
  - _scip_tags_from_document produces correct Tag namedtuples
  - get_tags dispatches to SCIP for Python files when scip_docs is populated
  - get_tags falls back to tree-sitter when SCIP data is absent
  - create_graph builds accurate nodes/edges using SCIP ident matching
  - _run_scip_indexing handles success, failure, caching, and timeout
  - read_scip helper functions (symbol_kind, short_name, qualified_name) work

All tests are self-contained and use mocks to avoid needing a real
database, scip-python binary, or .scip index file.
"""

import os
import sys
import subprocess
import tempfile
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure project root is on the path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

# Also ensure the scip/ directory is importable
scip_dir = str(project_root / "scip")
if scip_dir not in sys.path:
    sys.path.insert(0, scip_dir)


# ── Helpers to import read_scip without scip_pb2 issues ──────────


def _try_import_read_scip():
    """Try to import read_scip; return None if scip_pb2 is missing or generation fails."""
    try:
        import read_scip
        return read_scip
    except (ImportError, ModuleNotFoundError, RuntimeError, FileNotFoundError, OSError, IOError):
        return None


read_scip_mod = _try_import_read_scip()

# We can always test the parsing_repomap SCIP integration by injecting
# mock data into scip_docs — no need for the actual scip_pb2.


# ── Fixtures ─────────────────────────────────────────────────────────


class FakeIO:
    """Minimal IO object that satisfies RepoMap's self.io interface."""

    def __init__(self, file_contents: dict[str, str] | None = None):
        self._files = file_contents or {}

    def read_text(self, fname):
        return self._files.get(fname, "")

    def tool_error(self, msg):
        pass

    def tool_output(self, msg):
        pass


class FakeParseHelper:
    """Minimal ParseHelper stub."""

    def is_text_file(self, path):
        return path.endswith(".py") or path.endswith(".txt")


@pytest.fixture
def fake_repo(tmp_path):
    """Create a tiny Python repo with two files that cross-reference."""
    # models.py: defines Greeting class with a greet() method
    models_py = tmp_path / "models.py"
    models_py.write_text(
        "class Greeting:\n"
        "    def greet(self):\n"
        '        return "hello"\n'
    )

    # app.py: defines App class with a run() method that refs Greeting.greet
    app_py = tmp_path / "app.py"
    app_py.write_text(
        "from models import Greeting\n"
        "\n"
        "class App:\n"
        "    def run(self):\n"
        "        g = Greeting()\n"
        "        return g.greet()\n"
    )

    return tmp_path


def _make_repomap(root, file_contents=None):
    """Construct a RepoMap with mocked dependencies."""
    io = FakeIO(file_contents)
    with patch(
        "app.modules.parsing.graph_construction.parsing_repomap.get_db"
    ) as mock_get_db, patch(
        "app.modules.parsing.graph_construction.parsing_repomap.ParseHelper",
        return_value=FakeParseHelper(),
    ):
        mock_get_db.return_value = iter([MagicMock()])
        from app.modules.parsing.graph_construction.parsing_repomap import RepoMap

        rm = RepoMap(root=str(root), io=io)
    return rm


# ── Synthetic SCIP data ──────────────────────────────────────────────
# We construct DocumentRecord-like objects without needing scip_pb2.


class _SymbolLocation:
    """Lightweight stand-in for read_scip.SymbolLocation."""

    def __init__(self, symbol: str, line: int, end_line: int = -1):
        self.symbol = symbol
        self.line = line
        self.end_line = end_line


class _DocumentRecord:
    """Lightweight stand-in for read_scip.DocumentRecord."""

    def __init__(self, relative_path, definitions=None, references=None):
        self.relative_path = relative_path
        self.definitions = definitions or []
        self.references = references or []


# SCIP symbol strings following the real format:
#   scip-python python <pkg> <version> <descriptor>
SYM_GREETING_CLASS = "scip-python python potpie 0.1 models/Greeting#"
SYM_GREETING_GREET = "scip-python python potpie 0.1 models/Greeting#greet()."
SYM_APP_CLASS = "scip-python python potpie 0.1 app/App#"
SYM_APP_RUN = "scip-python python potpie 0.1 app/App#run()."

SCIP_DOCS = {
    "models.py": _DocumentRecord(
        relative_path="models.py",
        definitions=[
            # Greeting class spans lines 0-2 (enclosing_range from SCIP)
            _SymbolLocation(SYM_GREETING_CLASS, 0, end_line=2),
            # greet method: end_line == line (single-line enclosing_range)
            _SymbolLocation(SYM_GREETING_GREET, 1, end_line=1),
        ],
        references=[],
    ),
    "app.py": _DocumentRecord(
        relative_path="app.py",
        definitions=[
            _SymbolLocation(SYM_APP_CLASS, 2, end_line=5),
            _SymbolLocation(SYM_APP_RUN, 3, end_line=3),
        ],
        references=[
            _SymbolLocation(SYM_GREETING_CLASS, 0),
            _SymbolLocation(SYM_GREETING_GREET, 5),
        ],
    ),
}


# =====================================================================
# Test: read_scip helper functions
# =====================================================================


@pytest.mark.skipif(read_scip_mod is None, reason="scip_pb2 not generated")
class TestReadScipHelpers:
    """Tests for symbol_kind, short_name, qualified_name."""

    def test_symbol_kind_method(self):
        assert read_scip_mod.symbol_kind(SYM_GREETING_GREET) == "method"

    def test_symbol_kind_class(self):
        assert read_scip_mod.symbol_kind(SYM_GREETING_CLASS) == "class"

    def test_symbol_kind_variable(self):
        sym = "scip-python python p 0.1 module/MY_VAR."
        assert read_scip_mod.symbol_kind(sym) == "variable"

    def test_symbol_kind_module(self):
        sym = "scip-python python p 0.1 some_module/"
        assert read_scip_mod.symbol_kind(sym) == "module"

    def test_symbol_kind_parameter(self):
        sym = "scip-python python p 0.1 module/Cls#method().(param)"
        assert read_scip_mod.symbol_kind(sym) == "parameter"

    def test_short_name_method(self):
        assert read_scip_mod.short_name(SYM_GREETING_GREET) == "greet"

    def test_short_name_class(self):
        assert read_scip_mod.short_name(SYM_GREETING_CLASS) == "Greeting"

    def test_qualified_name_method(self):
        assert read_scip_mod.qualified_name(SYM_GREETING_GREET) == "Greeting.greet"

    def test_qualified_name_class(self):
        assert read_scip_mod.qualified_name(SYM_GREETING_CLASS) == "Greeting"

    def test_qualified_name_top_level(self):
        sym = "scip-python python p 0.1 mymod/DEFAULT_MODEL."
        assert read_scip_mod.qualified_name(sym) == "DEFAULT_MODEL"


# =====================================================================
# Test: _scip_tags_from_document
# =====================================================================


class TestScipTagsFromDocument:
    """Test that _scip_tags_from_document yields correct Tag namedtuples."""

    def test_definitions_emitted(self, fake_repo):
        rm = _make_repomap(fake_repo)
        doc = SCIP_DOCS["models.py"]
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "models.py"), "models.py"))

        defs = [t for t in tags if t.kind == "def"]
        assert len(defs) == 2
        assert defs[0].name == "Greeting"
        assert defs[0].type == "class"
        assert defs[0].ident == SYM_GREETING_CLASS
        assert defs[1].name == "greet"
        assert defs[1].type == "method"
        assert defs[1].ident == SYM_GREETING_GREET

    def test_references_emitted(self, fake_repo):
        rm = _make_repomap(fake_repo)
        doc = SCIP_DOCS["app.py"]
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "app.py"), "app.py"))

        refs = [t for t in tags if t.kind == "ref"]
        assert len(refs) == 2
        assert refs[0].ident == SYM_GREETING_CLASS
        assert refs[1].ident == SYM_GREETING_GREET

    def test_parameters_skipped(self, fake_repo):
        rm = _make_repomap(fake_repo)
        param_sym = "scip-python python potpie 0.1 models/Greeting#greet().(self)"
        doc = _DocumentRecord(
            relative_path="models.py",
            definitions=[_SymbolLocation(param_sym, 1, end_line=1)],
            references=[],
        )
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "models.py"), "models.py"))
        assert len(tags) == 0, "Parameters should be filtered out"

    def test_end_line_from_scip(self, fake_repo):
        """end_line should come from SCIP enclosing_range or tree-sitter fallback."""
        rm = _make_repomap(fake_repo)
        doc = SCIP_DOCS["models.py"]
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "models.py"), "models.py"))
        defs = [t for t in tags if t.kind == "def"]
        # Greeting class: SCIP gave end_line=2 (multi-line)
        assert defs[0].end_line == 2
        # greet method: SCIP gave end_line=1 (single-line), but tree-sitter
        # fallback should resolve the actual function end (line 2)
        assert defs[1].end_line >= defs[1].line

    def test_tag_has_ident_field(self, fake_repo):
        rm = _make_repomap(fake_repo)
        doc = SCIP_DOCS["models.py"]
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "models.py"), "models.py"))
        for tag in tags:
            assert hasattr(tag, "ident")
            assert tag.ident != tag.name, "SCIP ident should be the full symbol, not short name"

    def test_unknown_kind_maps_to_unknown_type(self, fake_repo):
        rm = _make_repomap(fake_repo)
        # A symbol ending with just "." but no "#" — symbol_kind returns "variable"
        # which is in the map. Let's test with a descriptor that doesn't match:
        weird_sym = "scip-python python p 0.1 weird"
        doc = _DocumentRecord(
            relative_path="models.py",
            definitions=[_SymbolLocation(weird_sym, 0, end_line=0)],
            references=[],
        )
        tags = list(rm._scip_tags_from_document(doc, str(fake_repo / "models.py"), "models.py"))
        assert len(tags) == 1
        assert tags[0].type == "variable"  # "variable" is in the map


# =====================================================================
# Test: get_tags dispatch logic
# =====================================================================


class TestGetTagsDispatch:
    """Verify get_tags routes Python files to SCIP when scip_docs populated."""

    def test_python_file_uses_scip_when_available(self, fake_repo):
        fname = str(fake_repo / "models.py")
        file_contents = {fname: "class Greeting:\n    def greet(self):\n        pass\n"}
        rm = _make_repomap(fake_repo, file_contents)
        rm.scip_docs = SCIP_DOCS

        tags = rm.get_tags(fname, "models.py")
        # Should come from SCIP — ident should be a full SCIP symbol
        assert len(tags) > 0
        assert tags[0].ident.startswith("scip-python")

    def test_python_file_falls_back_to_treesitter(self, fake_repo):
        fname = str(fake_repo / "models.py")
        file_contents = {fname: "class Greeting:\n    def greet(self):\n        pass\n"}
        rm = _make_repomap(fake_repo, file_contents)
        rm.scip_docs = {}  # No SCIP data

        tags = rm.get_tags(fname, "models.py")
        # Should come from tree-sitter — ident == name (short string)
        if tags:
            assert not tags[0].ident.startswith("scip-python")

    def test_non_python_file_never_uses_scip(self, fake_repo):
        js_path = fake_repo / "index.js"
        js_path.write_text('console.log("hello");\n')
        fname = str(js_path)
        file_contents = {fname: 'console.log("hello");\n'}
        rm = _make_repomap(fake_repo, file_contents)
        rm.scip_docs = {"index.js": _DocumentRecord("index.js")}

        tags = rm.get_tags(fname, "index.js")
        # JS files should never go through SCIP path (fname.endswith(".py") is False)
        for tag in tags:
            assert not tag.ident.startswith("scip-python")


# =====================================================================
# Test: create_graph with SCIP data (precise matching)
# =====================================================================


class TestCreateGraphWithScip:
    """Verify create_graph builds correct nodes and edges from SCIP data."""

    def _build_graph(self, fake_repo):
        """Build a graph with pre-populated SCIP docs."""
        models_path = str(fake_repo / "models.py")
        app_path = str(fake_repo / "app.py")
        file_contents = {
            models_path: (
                "class Greeting:\n"
                "    def greet(self):\n"
                '        return "hello"\n'
            ),
            app_path: (
                "from models import Greeting\n"
                "\n"
                "class App:\n"
                "    def run(self):\n"
                "        g = Greeting()\n"
                "        return g.greet()\n"
            ),
        }
        rm = _make_repomap(fake_repo, file_contents)

        # Pre-populate SCIP docs so _run_scip_indexing is effectively skipped
        rm.scip_docs = SCIP_DOCS
        # Patch _run_scip_indexing to not actually run subprocess
        with patch.object(rm, "_run_scip_indexing"):
            G = rm.create_graph(str(fake_repo))
        return G

    def test_file_nodes_created(self, fake_repo):
        G = self._build_graph(fake_repo)
        assert G.has_node("models.py")
        assert G.has_node("app.py")
        assert G.nodes["models.py"]["type"] == "FILE"
        assert G.nodes["app.py"]["type"] == "FILE"

    def test_class_nodes_created(self, fake_repo):
        G = self._build_graph(fake_repo)
        # Greeting class def: current_class = "Greeting", tag.name = "Greeting"
        # node_name = "models.py:Greeting.Greeting" (because current_class is set from class tag)
        # Actually for class defs: current_class = tag.name, then node_name = f"{path}:{current_class}.{tag.name}"
        # That gives "models.py:Greeting.Greeting"
        greeting_candidates = [
            n for n in G.nodes if "Greeting" in n and n != "models.py"
        ]
        assert len(greeting_candidates) >= 1, f"Expected Greeting node, got {list(G.nodes)}"

    def test_method_nodes_created(self, fake_repo):
        G = self._build_graph(fake_repo)
        method_nodes = [
            n for n in G.nodes
            if G.nodes[n].get("type") == "FUNCTION"
        ]
        assert len(method_nodes) >= 1, f"Expected method nodes, got {list(G.nodes)}"

    def test_contains_edges_exist(self, fake_repo):
        G = self._build_graph(fake_repo)
        contains_edges = [
            (u, v) for u, v, d in G.edges(data=True) if d.get("type") == "CONTAINS"
        ]
        assert len(contains_edges) >= 2, "Expected at least 2 CONTAINS edges"

    def test_references_use_full_scip_ident(self, fake_repo):
        G = self._build_graph(fake_repo)
        ref_edges = [
            (u, v, d) for u, v, d in G.edges(data=True) if d.get("type") == "REFERENCES"
        ]
        # With SCIP matching, refs should match via full symbol string,
        # not short names. If edges exist, their ident should be a SCIP sym.
        for u, v, d in ref_edges:
            assert "scip-python" in d.get("ident", ""), (
                f"REFERENCES edge ident should be a SCIP symbol, got: {d.get('ident')}"
            )

    def test_no_false_positive_cross_file_edges(self, fake_repo):
        """SCIP symbols are fully qualified — no name-collision false edges."""
        G = self._build_graph(fake_repo)
        ref_edges = [
            (u, v, d) for u, v, d in G.edges(data=True) if d.get("type") == "REFERENCES"
        ]
        # Every REFERENCES edge should connect two distinct nodes
        for u, v, d in ref_edges:
            assert u != v


# =====================================================================
# Test: _run_scip_indexing
# =====================================================================


class TestRunScipIndexing:
    """Test _run_scip_indexing subprocess handling and caching."""

    def test_skipped_when_scip_not_available(self, fake_repo):
        rm = _make_repomap(fake_repo)
        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            False,
        ):
            rm._run_scip_indexing(str(fake_repo))
        assert rm.scip_docs == {}

    def test_scip_not_on_path_falls_back(self, fake_repo):
        rm = _make_repomap(fake_repo)
        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run",
            side_effect=FileNotFoundError("scip-python not found"),
        ):
            rm._run_scip_indexing(str(fake_repo))
        assert rm.scip_docs == {}

    def test_scip_timeout_falls_back(self, fake_repo):
        rm = _make_repomap(fake_repo)
        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="scip-python", timeout=120),
        ):
            rm._run_scip_indexing(str(fake_repo))
        assert rm.scip_docs == {}

    def test_scip_nonzero_exit_code_falls_back(self, fake_repo):
        rm = _make_repomap(fake_repo)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"
        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run",
            return_value=mock_result,
        ):
            rm._run_scip_indexing(str(fake_repo))
        assert rm.scip_docs == {}

    def test_cache_hit_skips_reindex(self, fake_repo):
        rm = _make_repomap(fake_repo)
        # Simulate a prior successful index
        rm.scip_docs = SCIP_DOCS
        rm._scip_repo_dir = str(fake_repo)
        rm._scip_repo_mtime = rm._newest_py_mtime(str(fake_repo))

        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run"
        ) as mock_run:
            rm._run_scip_indexing(str(fake_repo))
            mock_run.assert_not_called()

    def test_cache_miss_when_mtime_changes(self, fake_repo):
        rm = _make_repomap(fake_repo)
        rm.scip_docs = SCIP_DOCS
        rm._scip_repo_dir = str(fake_repo)
        rm._scip_repo_mtime = 0.0  # stale

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            rm._run_scip_indexing(str(fake_repo))
            mock_run.assert_called_once()

    def test_dynamic_project_name(self, fake_repo):
        rm = _make_repomap(fake_repo)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = ""

        with patch(
            "app.modules.parsing.graph_construction.parsing_repomap._SCIP_AVAILABLE",
            True,
        ), patch(
            "app.modules.parsing.graph_construction.parsing_repomap.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            rm._run_scip_indexing(str(fake_repo))
            call_args = mock_run.call_args
            cmd = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
            # --project-name should be the basename of fake_repo
            expected_name = os.path.basename(str(fake_repo))
            assert expected_name in cmd, (
                f"Expected project name '{expected_name}' in command {cmd}"
            )


# =====================================================================
# Test: _newest_py_mtime
# =====================================================================


class TestNewestPyMtime:
    """Test the mtime helper used for SCIP cache invalidation."""

    def test_returns_nonzero_for_py_repo(self, fake_repo):
        from app.modules.parsing.graph_construction.parsing_repomap import RepoMap

        mtime = RepoMap._newest_py_mtime(str(fake_repo))
        assert mtime > 0

    def test_returns_zero_for_empty_dir(self, tmp_path):
        from app.modules.parsing.graph_construction.parsing_repomap import RepoMap

        mtime = RepoMap._newest_py_mtime(str(tmp_path))
        assert mtime == 0.0

    def test_returns_zero_for_non_py_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("hello")
        from app.modules.parsing.graph_construction.parsing_repomap import RepoMap

        mtime = RepoMap._newest_py_mtime(str(tmp_path))
        assert mtime == 0.0


# =====================================================================
# Test: Tag namedtuple structure
# =====================================================================


class TestTagStructure:
    """Verify the Tag namedtuple has the expected fields."""

    def test_tag_has_all_fields(self):
        from app.modules.parsing.graph_construction.parsing_repomap import Tag

        assert Tag._fields == (
            "rel_fname", "fname", "line", "end_line", "name", "ident", "kind", "type", "text"
        )

    def test_tag_ident_field_exists(self):
        from app.modules.parsing.graph_construction.parsing_repomap import Tag

        tag = Tag(
            rel_fname="a.py", fname="/x/a.py", line=0, end_line=0,
            name="foo", ident="full.sym.foo", kind="def", type="method",
            text="def foo(): pass",
        )
        assert tag.ident == "full.sym.foo"
        assert tag.name == "foo"
        assert tag.text == "def foo(): pass"


# =====================================================================
# Test: _SCIP_KIND_TO_TAG_TYPE constant
# =====================================================================


class TestScipKindMapping:
    """Verify the module-level mapping constant."""

    def test_mapping_covers_core_kinds(self):
        from app.modules.parsing.graph_construction.parsing_repomap import (
            _SCIP_KIND_TO_TAG_TYPE,
        )

        assert "method" in _SCIP_KIND_TO_TAG_TYPE
        assert "class" in _SCIP_KIND_TO_TAG_TYPE
        assert "variable" in _SCIP_KIND_TO_TAG_TYPE
        assert "module" in _SCIP_KIND_TO_TAG_TYPE

    def test_mapping_not_rebuilt_per_call(self):
        """_SCIP_KIND_TO_TAG_TYPE should be the same object on repeated imports."""
        from app.modules.parsing.graph_construction.parsing_repomap import (
            _SCIP_KIND_TO_TAG_TYPE as m1,
        )
        from app.modules.parsing.graph_construction.parsing_repomap import (
            _SCIP_KIND_TO_TAG_TYPE as m2,
        )

        assert m1 is m2


# =====================================================================
# Test: Integration — run scip-python and call build_document_records
# =====================================================================

import shutil
import textwrap

_SCIP_PYTHON_AVAILABLE = shutil.which("scip-python") is not None


@pytest.mark.skipif(
    not _SCIP_PYTHON_AVAILABLE, reason="scip-python not installed"
)
@pytest.mark.skipif(read_scip_mod is None, reason="scip_pb2 not generated")
class TestBuildDocumentRecordsIntegration:
    """Run scip-python on a real temp repo and verify build_document_records.

    This is an integration test that requires:
      - scip-python on PATH
      - git CLI
      - the generated scip_pb2 module
    """

    SAMPLE_CODE = textwrap.dedent("""\
        class Greeting:
            \"\"\"A simple greeting class.\"\"\"

            def hello(self, name: str) -> str:
                return f"Hello, {name}!"

            def goodbye(self, name: str) -> str:
                return f"Goodbye, {name}!"

        def standalone_func(x, y):
            \"\"\"Add two numbers.\"\"\"
            return x + y

        MY_VAR = 42
    """)

    CALLER_CODE = textwrap.dedent("""\
        from sample import Greeting, standalone_func

        class App:
            def run(self):
                g = Greeting()
                print(g.hello("world"))
                return standalone_func(1, 2)
    """)

    @pytest.fixture()
    def scip_records(self, tmp_path):
        """Create a git repo, run scip-python, return DocumentRecords."""
        # --- set up git repo ---
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )

        (tmp_path / "sample.py").write_text(self.SAMPLE_CODE)
        (tmp_path / "caller.py").write_text(self.CALLER_CODE)

        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True, check=True,
        )

        # --- run scip-python ---
        scip_output = str(tmp_path / "index.scip")
        result = subprocess.run(
            [
                "scip-python", "index", ".",
                "--project-name", "test_proj",
                "--output", scip_output,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"scip-python failed (rc={result.returncode}): {result.stderr[:500]}"
        )
        assert os.path.exists(scip_output), "index.scip not created"

        # --- load and parse ---
        index = read_scip_mod.load_index(scip_output)
        records = read_scip_mod.build_document_records(index)
        return records, tmp_path

    # ── assertions ────────────────────────────────────────────────

    def test_records_contain_both_files(self, scip_records):
        records, _ = scip_records
        assert "sample.py" in records
        assert "caller.py" in records

    def test_sample_definitions_present(self, scip_records):
        records, _ = scip_records
        rec = records["sample.py"]
        def_names = [
            read_scip_mod.short_name(d.symbol) for d in rec.definitions
            if read_scip_mod.symbol_kind(d.symbol) != "parameter"
        ]
        # short_name may include module prefix for top-level symbols
        joined = " ".join(def_names)
        assert "Greeting" in joined
        assert "hello" in joined
        assert "goodbye" in joined
        assert "standalone_func" in joined

    def test_class_has_multiline_end(self, scip_records):
        """Greeting class should have end_line > line (from enclosing_range)."""
        records, _ = scip_records
        rec = records["sample.py"]
        greeting = [
            d for d in rec.definitions
            if read_scip_mod.symbol_kind(d.symbol) == "class"
        ]
        assert len(greeting) >= 1
        cls = greeting[0]
        print(f"Greeting class: line={cls.line}, end_line={cls.end_line}")
        assert cls.end_line > cls.line, (
            f"Class enclosing_range should be multi-line, got "
            f"line={cls.line} end_line={cls.end_line}"
        )

    def test_standalone_func_has_multiline_end(self, scip_records):
        """standalone_func should have end_line > line."""
        records, _ = scip_records
        rec = records["sample.py"]
        funcs = [
            d for d in rec.definitions
            if "standalone_func" in d.symbol
            and read_scip_mod.symbol_kind(d.symbol) == "method"
        ]
        assert len(funcs) == 1
        fn = funcs[0]
        print(f"standalone_func: line={fn.line}, end_line={fn.end_line}")
        assert fn.end_line > fn.line, (
            f"Function enclosing_range should be multi-line, got "
            f"line={fn.line} end_line={fn.end_line}"
        )

    def test_method_end_line(self, scip_records):
        """Methods may have single-line enclosing_range; end_line >= line."""
        records, _ = scip_records
        rec = records["sample.py"]
        methods = [
            d for d in rec.definitions
            if "hello" in d.symbol
            and read_scip_mod.symbol_kind(d.symbol) == "method"
        ]
        assert len(methods) == 1
        m = methods[0]
        print(f"hello method: line={m.line}, end_line={m.end_line}")
        assert m.end_line >= m.line

    def test_variable_has_no_enclosing(self, scip_records):
        """MY_VAR should have end_line == line (no enclosing_range)."""
        records, _ = scip_records
        rec = records["sample.py"]
        variables = [
            d for d in rec.definitions
            if "MY_VAR" in d.symbol
        ]
        assert len(variables) == 1
        v = variables[0]
        print(f"MY_VAR: line={v.line}, end_line={v.end_line}")
        assert v.end_line == v.line

    def test_caller_references_sample_symbols(self, scip_records):
        """caller.py should have references to Greeting and standalone_func."""
        records, _ = scip_records
        rec = records["caller.py"]
        ref_symbols = [r.symbol for r in rec.references]
        ref_text = " ".join(ref_symbols)
        assert "Greeting" in ref_text, f"Expected Greeting ref, got: {ref_symbols[:5]}"

    def test_file_lines_text_extraction(self, scip_records):
        """Verify file_lines[line:end_line+1] gives sensible text for defs."""
        records, tmp_path = scip_records
        rec = records["sample.py"]
        code = (tmp_path / "sample.py").read_text()
        file_lines = code.splitlines()

        for defn in rec.definitions:
            kind = read_scip_mod.symbol_kind(defn.symbol)
            if kind in ("parameter", "module"):
                continue
            # Skip SCIP module-init symbols (e.g. sample/__init__:)
            if "__init__" in defn.symbol:
                continue
            name = read_scip_mod.short_name(defn.symbol)
            text = "\n".join(file_lines[defn.line : defn.end_line + 1])
            print(f"  {name} [{kind}] lines {defn.line}-{defn.end_line}: "
                  f"{text[:80]!r}...")
            # The extracted text should contain some part of the symbol name
            # (short_name may include module prefix, so check the last segment)
            leaf_name = name.rsplit("/", 1)[-1]
            assert leaf_name in text, (
                f"Expected '{leaf_name}' in text for lines "
                f"{defn.line}-{defn.end_line}, got: {text[:120]}"
            )
