"""Unit tests for code graph construction improvements.

Covers three new relationship types added in feat/class-methods:
  - CONTAINS   (class → member method)
  - EXTENDS    (subclass → base class)
  - IMPORTS    (source file → target file when a cross-file reference exists)

All tests are fully isolated: no database, Redis, or Neo4j required.
"""

from __future__ import annotations

import os
import sys
import types
from collections import namedtuple
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

# ---------------------------------------------------------------------------
# Minimal stub for ParseHelper / get_db so RepoMap can be imported without a
# live database connection.
# ---------------------------------------------------------------------------

_parse_helper_stub = MagicMock()
_get_db_stub = MagicMock(return_value=iter([MagicMock()]))

# We must patch *before* the module is first imported.
with (
    patch("app.core.database.get_db", _get_db_stub),
    patch(
        "app.modules.parsing.graph_construction.parsing_helper.ParseHelper",
        return_value=_parse_helper_stub,
    ),
):
    from app.modules.parsing.graph_construction.parsing_repomap import RepoMap, Tag

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tag(
    *,
    rel_fname="src/module.py",
    fname="/repo/src/module.py",
    line=0,
    end_line=0,
    name="symbol",
    ident="symbol",
    kind="def",
    type="function",
    base=None,
    text="",
) -> Tag:
    """Convenience factory for Tag namedtuples."""
    return Tag(
        rel_fname=rel_fname,
        fname=fname,
        line=line,
        end_line=end_line,
        name=name,
        ident=ident,
        kind=kind,
        type=type,
        base=base if base is not None else [],
        text=text,
    )


def _make_repo_map() -> RepoMap:
    """Create a RepoMap instance with minimal stubs."""
    io_stub = MagicMock()
    io_stub.read_text.return_value = ""

    with (
        patch("app.core.database.get_db", _get_db_stub),
        patch(
            "app.modules.parsing.graph_construction.parsing_repomap.ParseHelper",
            return_value=_parse_helper_stub,
        ),
    ):
        rm = RepoMap.__new__(RepoMap)
        rm.io = io_stub
        rm.verbose = False
        rm.root = "/repo"
        rm.max_map_tokens = 1024
        rm.map_mul_no_files = 8
        rm.max_context_window = None
        rm.repo_content_prefix = None
        rm.parse_helper = MagicMock()
        rm.parse_helper.is_text_file.return_value = True
        rm.scip_docs = {}
        rm._scip_repo_dir = None
        rm._scip_repo_mtime = None
        rm.tree_cache = {}
    return rm


# ===========================================================================
# 1. Tests for create_relationship() — static helper
# ===========================================================================

class TestCreateRelationship:
    """Tests for the create_relationship static helper."""

    def _graph_with_nodes(self, *nodes_and_types):
        """Build a MultiDiGraph whose nodes carry a 'type' attribute."""
        G = nx.MultiDiGraph()
        for name, ntype in nodes_and_types:
            G.add_node(name, type=ntype)
        return G

    # ------------------------------------------------------------------
    # CONTAINS
    # Note: CONTAINS edges are added directly via G.add_edge() in create_graph,
    # bypassing create_relationship().  These tests document that boundary.
    # The actual CONTAINS behaviour is verified in TestCreateGraphContains.
    # ------------------------------------------------------------------

    def test_contains_not_handled_by_create_relationship_file_to_func(self):
        """create_relationship does not handle CONTAINS; it returns False.
        CONTAINS edges from file → symbol are added directly in create_graph."""
        G = self._graph_with_nodes(
            ("src/a.py", "FILE"),
            ("src/a.py:MyFunc", "FUNCTION"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G, "src/a.py", "src/a.py:MyFunc", "CONTAINS", seen
        )
        # create_relationship has no CONTAINS branch → returns False
        assert result is False
        assert len(list(G.edges())) == 0

    def test_contains_not_handled_by_create_relationship_class_to_method(self):
        """create_relationship does not handle CONTAINS; it returns False.
        CONTAINS edges from class → method are added directly in create_graph."""
        G = self._graph_with_nodes(
            ("src/a.py:MyClass", "CLASS"),
            ("src/a.py:MyClass.my_method", "FUNCTION"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G,
            "src/a.py:MyClass",
            "src/a.py:MyClass.my_method",
            "CONTAINS",
            seen,
        )
        assert result is False
        assert len(list(G.edges())) == 0

    # ------------------------------------------------------------------
    # EXTENDS
    # ------------------------------------------------------------------

    def test_extends_added_between_classes(self):
        G = self._graph_with_nodes(
            ("src/a.py:Child", "CLASS"),
            ("src/b.py:Parent", "CLASS"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G,
            "src/a.py:Child",
            "src/b.py:Parent",
            "EXTENDS",
            seen,
            {"indent": "Parent"},
        )
        assert result is True
        edge_data = [d for _, _, d in G.edges(data=True)]
        assert any(d["type"] == "EXTENDS" for d in edge_data)

    def test_extends_self_loop_rejected(self):
        G = self._graph_with_nodes(("src/a.py:MyClass", "CLASS"))
        seen = set()
        result = RepoMap.create_relationship(
            G,
            "src/a.py:MyClass",
            "src/a.py:MyClass",
            "EXTENDS",
            seen,
        )
        assert result is False
        assert len(list(G.edges())) == 0

    def test_extends_duplicate_rejected(self):
        G = self._graph_with_nodes(
            ("src/a.py:Child", "CLASS"),
            ("src/b.py:Parent", "CLASS"),
        )
        seen = set()
        RepoMap.create_relationship(G, "src/a.py:Child", "src/b.py:Parent", "EXTENDS", seen)
        # Second call with same edge should be rejected
        result = RepoMap.create_relationship(
            G, "src/a.py:Child", "src/b.py:Parent", "EXTENDS", seen
        )
        assert result is False
        assert len(list(G.edges())) == 1  # only the first edge

    def test_extends_reverse_duplicate_rejected(self):
        """Reverse direction also counts as a duplicate to prevent bidirectional EXTENDS."""
        G = self._graph_with_nodes(
            ("src/a.py:Child", "CLASS"),
            ("src/b.py:Parent", "CLASS"),
        )
        seen = set()
        RepoMap.create_relationship(G, "src/a.py:Child", "src/b.py:Parent", "EXTENDS", seen)
        result = RepoMap.create_relationship(
            G, "src/b.py:Parent", "src/a.py:Child", "EXTENDS", seen
        )
        assert result is False

    # ------------------------------------------------------------------
    # IMPORTS
    # ------------------------------------------------------------------

    def test_imports_added_between_files(self):
        G = self._graph_with_nodes(
            ("src/a.py", "FILE"),
            ("src/b.py", "FILE"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G,
            "src/a.py",
            "src/b.py",
            "IMPORTS",
            seen,
            {"ident": "helper_func", "ref_line": 3, "end_ref_line": 3},
        )
        assert result is True
        edge_data = [d for _, _, d in G.edges(data=True)]
        assert any(d["type"] == "IMPORTS" for d in edge_data)

    def test_imports_self_loop_rejected(self):
        G = self._graph_with_nodes(("src/a.py", "FILE"))
        seen = set()
        result = RepoMap.create_relationship(
            G, "src/a.py", "src/a.py", "IMPORTS", seen
        )
        assert result is False

    def test_imports_duplicate_rejected(self):
        G = self._graph_with_nodes(
            ("src/a.py", "FILE"),
            ("src/b.py", "FILE"),
        )
        seen = set()
        RepoMap.create_relationship(G, "src/a.py", "src/b.py", "IMPORTS", seen)
        result = RepoMap.create_relationship(G, "src/a.py", "src/b.py", "IMPORTS", seen)
        assert result is False
        assert len(list(G.edges())) == 1

    # ------------------------------------------------------------------
    # REFERENCES direction validation (pre-existing behaviour, sanity-check)
    # ------------------------------------------------------------------

    def test_references_function_to_function_accepted(self):
        G = self._graph_with_nodes(
            ("src/a.py:caller", "FUNCTION"),
            ("src/b.py:callee", "FUNCTION"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G, "src/a.py:caller", "src/b.py:callee", "REFERENCES", seen
        )
        assert result is True

    def test_references_invalid_direction_rejected(self):
        """FILE → FILE REFERENCES should be rejected (not a valid direction)."""
        G = self._graph_with_nodes(
            ("src/a.py", "FILE"),
            ("src/b.py", "FILE"),
        )
        seen = set()
        result = RepoMap.create_relationship(
            G, "src/a.py", "src/b.py", "REFERENCES", seen
        )
        assert result is False


# ===========================================================================
# 2. Tests for create_graph() — integration-style unit tests
# ===========================================================================

_IGNORE_SPEC_PATH = "app.modules.code_provider.ignore_spec.load_ignore_spec"


def _run_create_graph(file_tags_map: dict[str, list[Tag]], file_texts: dict[str, str]):
    """
    Run RepoMap.create_graph on a virtual repo.

    Parameters
    ----------
    file_tags_map : { rel_path: [Tag, ...] }
        Tags returned by get_tags() per file.
    file_texts : { rel_path: str }
        Raw file text returned by io.read_text().

    Returns
    -------
    nx.MultiDiGraph
    """
    repo_dir = "/repo"
    rm = _make_repo_map()

    # Patch os.walk to yield the virtual file tree
    abs_file_map = {
        os.path.join(repo_dir, rel): rel for rel in file_tags_map
    }

    def fake_walk(root, **kwargs):
        by_dir: dict[str, list[str]] = {}
        for abs_path in abs_file_map:
            d = os.path.dirname(abs_path)
            by_dir.setdefault(d, []).append(os.path.basename(abs_path))
        for directory, files in by_dir.items():
            yield directory, [], files

    # All files are text files
    rm.parse_helper.is_text_file.return_value = True

    def fake_get_tags(fname, rel_fname):
        return file_tags_map.get(rel_fname, [])

    def fake_read_text(path):
        rel = os.path.relpath(path, repo_dir)
        return file_texts.get(rel, "")

    def fake_get_mtime(fname):
        return 1.0

    rm.get_tags = fake_get_tags
    rm.get_mtime = fake_get_mtime
    rm.io.read_text.side_effect = fake_read_text

    with (
        patch("os.walk", side_effect=fake_walk),
        patch(_IGNORE_SPEC_PATH, return_value=None),
    ):
        return rm.create_graph(repo_dir)


class TestCreateGraphContains:
    """create_graph should emit CONTAINS edges: class → member method."""

    def test_class_to_method_contains_edge(self):
        file_rel = "src/animals.py"
        tags = [
            _make_tag(
                rel_fname=file_rel,
                fname=f"/repo/{file_rel}",
                name="Animal",
                ident="Animal",
                kind="def",
                type="class",
                line=0,
                end_line=10,
            ),
            _make_tag(
                rel_fname=file_rel,
                fname=f"/repo/{file_rel}",
                name="speak",
                ident="speak",
                kind="def",
                type="method",
                line=2,
                end_line=5,
            ),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        class_node = f"{file_rel}:Animal"
        method_node = f"{file_rel}:Animal.speak"

        assert G.has_node(class_node), "CLASS node must exist"
        assert G.has_node(method_node), "method node must exist"

        edge_types = {d["type"] for _, _, d in G.edges(data=True)}
        assert "CONTAINS" in edge_types

        # Specifically verify class → method CONTAINS edge
        contains_edges = [
            (u, v)
            for u, v, d in G.edges(data=True)
            if d.get("type") == "CONTAINS" and u == class_node and v == method_node
        ]
        assert len(contains_edges) == 1, (
            f"Expected exactly one CONTAINS edge {class_node!r} → {method_node!r}, "
            f"got {contains_edges}"
        )

    def test_multiple_methods_each_get_contains_edge(self):
        file_rel = "src/shapes.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Shape",
                      kind="def", type="class", line=0, end_line=20),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="area",
                      kind="def", type="method", line=2, end_line=5),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="perimeter",
                      kind="def", type="method", line=7, end_line=10),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        class_node = f"{file_rel}:Shape"
        for method in ("area", "perimeter"):
            method_node = f"{file_rel}:Shape.{method}"
            contains = [
                (u, v) for u, v, d in G.edges(data=True)
                if d.get("type") == "CONTAINS" and u == class_node and v == method_node
            ]
            assert len(contains) == 1, f"Missing CONTAINS edge to {method_node!r}"

    def test_top_level_function_has_no_class_contains_from_class(self):
        """A function defined outside any class should NOT get a class CONTAINS edge."""
        file_rel = "src/utils.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="helper",
                      kind="def", type="function", line=0, end_line=5),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        # File → function CONTAINS is expected
        file_to_func = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "CONTAINS" and u == file_rel
        ]
        assert len(file_to_func) == 1

        # No class node should exist
        class_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "CLASS"]
        assert class_nodes == []

    def test_method_outside_class_scope_not_attributed_to_class(self):
        """A method tag whose line exceeds the class end_line must not get
        a CONTAINS edge from that class."""
        file_rel = "src/mixed.py"
        tags = [
            # Class occupies lines 0–5
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Foo",
                      kind="def", type="class", line=0, end_line=5),
            # Function at line 10 is OUTSIDE the class scope
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="standalone",
                      kind="def", type="function", line=10, end_line=12),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        class_node = f"{file_rel}:Foo"
        # standalone is outside class scope → node name should be "src/mixed.py:standalone"
        standalone_node = f"{file_rel}:standalone"
        assert G.has_node(standalone_node), "standalone function node must exist"

        # No CONTAINS from class to standalone
        bad_edges = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "CONTAINS" and u == class_node and v == standalone_node
        ]
        assert bad_edges == []


class TestCreateGraphExtends:
    """create_graph should emit EXTENDS edges: subclass → base class."""

    def test_extends_same_file(self):
        file_rel = "src/animals.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Animal",
                      ident="Animal", kind="def", type="class", line=0, end_line=5),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Dog",
                      ident="Dog", kind="def", type="class", line=7, end_line=15,
                      base=["Animal"]),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        base_node = f"{file_rel}:Animal"
        sub_node = f"{file_rel}:Dog"
        assert G.has_node(base_node)
        assert G.has_node(sub_node)

        extends_edges = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "EXTENDS" and u == sub_node and v == base_node
        ]
        assert len(extends_edges) == 1, (
            f"Expected EXTENDS {sub_node!r} → {base_node!r}, got {extends_edges}"
        )

    def test_extends_cross_file(self):
        base_rel = "src/base.py"
        sub_rel = "src/derived.py"
        tags = {
            base_rel: [
                _make_tag(rel_fname=base_rel, fname=f"/repo/{base_rel}",
                          name="Base", ident="Base", kind="def", type="class",
                          line=0, end_line=10),
            ],
            sub_rel: [
                _make_tag(rel_fname=sub_rel, fname=f"/repo/{sub_rel}",
                          name="Derived", ident="Derived", kind="def", type="class",
                          line=0, end_line=8, base=["Base"]),
            ],
        }
        G = _run_create_graph(tags, {base_rel: "", sub_rel: ""})

        base_node = f"{base_rel}:Base"
        sub_node = f"{sub_rel}:Derived"
        extends_edges = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "EXTENDS" and u == sub_node and v == base_node
        ]
        assert len(extends_edges) == 1

    def test_no_extends_when_base_undefined(self):
        """If the base class is not defined in the graph, no EXTENDS edge is created."""
        file_rel = "src/orphan.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Orphan",
                      ident="Orphan", kind="def", type="class", line=0, end_line=5,
                      base=["UnknownBase"]),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        extends_edges = [
            (u, v) for u, v, d in G.edges(data=True) if d.get("type") == "EXTENDS"
        ]
        assert extends_edges == []

    def test_extends_not_confused_with_references(self):
        """When A EXTENDS B, no extra REFERENCES edge should be added for the same pair."""
        file_rel = "src/hierarchy.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Base",
                      ident="Base", kind="def", type="class", line=0, end_line=5),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Child",
                      ident="Child", kind="def", type="class", line=7, end_line=15,
                      base=["Base"]),
            # A ref tag simulating that Child references Base (e.g. super())
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}", name="Base",
                      ident="Base", kind="ref", type="class", line=8, end_line=8),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        child_node = f"{file_rel}:Child"
        base_node = f"{file_rel}:Base"
        # Exactly one edge between Child → Base (the EXTENDS one, not REFERENCES)
        child_to_base = [
            d for u, v, d in G.edges(data=True) if u == child_node and v == base_node
        ]
        # Should be EXTENDS only, not REFERENCES
        edge_type_names = {d.get("type") for d in child_to_base}
        assert "EXTENDS" in edge_type_names
        assert "REFERENCES" not in edge_type_names, (
            "REFERENCES should not be added when an EXTENDS already exists for the same pair"
        )


class TestCreateGraphImports:
    """create_graph should emit IMPORTS edges: file_a → file_b when file_a
    references a symbol defined in file_b."""

    def test_imports_edge_created_for_cross_file_reference(self):
        file_a = "src/consumer.py"
        file_b = "src/provider.py"
        tags = {
            file_b: [
                _make_tag(rel_fname=file_b, fname=f"/repo/{file_b}",
                          name="helper", ident="helper", kind="def", type="function",
                          line=0, end_line=5),
            ],
            file_a: [
                # file_a defines its own function
                _make_tag(rel_fname=file_a, fname=f"/repo/{file_a}",
                          name="main", ident="main", kind="def", type="function",
                          line=0, end_line=10),
                # file_a references helper from file_b
                _make_tag(rel_fname=file_a, fname=f"/repo/{file_a}",
                          name="helper", ident="helper", kind="ref", type="function",
                          line=5, end_line=5),
            ],
        }
        G = _run_create_graph(tags, {file_a: "", file_b: ""})

        assert G.has_node(file_a), f"FILE node {file_a!r} must exist"
        assert G.has_node(file_b), f"FILE node {file_b!r} must exist"

        imports_edges = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "IMPORTS" and u == file_a and v == file_b
        ]
        assert len(imports_edges) >= 1, (
            f"Expected IMPORTS {file_a!r} → {file_b!r}, found {imports_edges}"
        )

    def test_no_imports_for_same_file_reference(self):
        """References within the same file must NOT produce IMPORTS edges."""
        file_rel = "src/self_contained.py"
        tags = [
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}",
                      name="util", ident="util", kind="def", type="function",
                      line=0, end_line=5),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}",
                      name="run", ident="run", kind="def", type="function",
                      line=7, end_line=12),
            _make_tag(rel_fname=file_rel, fname=f"/repo/{file_rel}",
                      name="util", ident="util", kind="ref", type="function",
                      line=9, end_line=9),
        ]
        G = _run_create_graph({file_rel: tags}, {file_rel: ""})

        imports_edges = [
            (u, v) for u, v, d in G.edges(data=True) if d.get("type") == "IMPORTS"
        ]
        assert imports_edges == [], (
            f"Self-file references must not create IMPORTS edges, got {imports_edges}"
        )

    def test_imports_edge_not_duplicated(self):
        """Multiple references from file_a to symbols in file_b should produce
        only one IMPORTS edge between the two file nodes."""
        file_a = "src/client.py"
        file_b = "src/library.py"
        tags = {
            file_b: [
                _make_tag(rel_fname=file_b, fname=f"/repo/{file_b}",
                          name="foo", ident="foo", kind="def", type="function",
                          line=0, end_line=3),
                _make_tag(rel_fname=file_b, fname=f"/repo/{file_b}",
                          name="bar", ident="bar", kind="def", type="function",
                          line=5, end_line=8),
            ],
            file_a: [
                _make_tag(rel_fname=file_a, fname=f"/repo/{file_a}",
                          name="main", ident="main", kind="def", type="function",
                          line=0, end_line=10),
                _make_tag(rel_fname=file_a, fname=f"/repo/{file_a}",
                          name="foo", ident="foo", kind="ref", type="function",
                          line=3, end_line=3),
                _make_tag(rel_fname=file_a, fname=f"/repo/{file_a}",
                          name="bar", ident="bar", kind="ref", type="function",
                          line=4, end_line=4),
            ],
        }
        G = _run_create_graph(tags, {file_a: "", file_b: ""})

        imports_edges = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("type") == "IMPORTS" and u == file_a and v == file_b
        ]
        # MultiDiGraph allows parallel edges, but seen_relationships deduplication
        # should prevent more than one IMPORTS edge between the same pair.
        assert len(imports_edges) == 1, (
            f"Expected exactly 1 IMPORTS edge, got {len(imports_edges)}: {imports_edges}"
        )

    def test_imports_direction_is_consumer_to_provider(self):
        """The IMPORTS edge must go from the file that uses the symbol (consumer)
        to the file that defines it (provider), not the other way around."""
        consumer = "src/consumer.py"
        provider = "src/provider.py"
        tags = {
            provider: [
                _make_tag(rel_fname=provider, fname=f"/repo/{provider}",
                          name="api_call", ident="api_call", kind="def", type="function",
                          line=0, end_line=5),
            ],
            consumer: [
                _make_tag(rel_fname=consumer, fname=f"/repo/{consumer}",
                          name="run", ident="run", kind="def", type="function",
                          line=0, end_line=10),
                _make_tag(rel_fname=consumer, fname=f"/repo/{consumer}",
                          name="api_call", ident="api_call", kind="ref", type="function",
                          line=5, end_line=5),
            ],
        }
        G = _run_create_graph(tags, {consumer: "", provider: ""})

        imports_edges = [(u, v) for u, v, d in G.edges(data=True)
                         if d.get("type") == "IMPORTS"]
        assert (consumer, provider) in imports_edges, (
            "IMPORTS must point FROM consumer TO provider"
        )
        # Reverse direction must NOT exist
        assert (provider, consumer) not in imports_edges, (
            "IMPORTS must not point FROM provider TO consumer"
        )


# ===========================================================================
# 3. Combined / edge-case tests
# ===========================================================================

class TestCreateGraphCombined:
    """Smoke tests combining multiple relationship types in one graph."""

    def test_all_three_relationship_types_present(self):
        """
        Repo layout:
          base.py   → defines BaseClass
          derived.py → defines DerivedClass(BaseClass) with method process()
                       also references BaseClass
        Expected edges:
          - base.py CONTAINS base.py:BaseClass
          - derived.py CONTAINS derived.py:DerivedClass
          - derived.py CONTAINS derived.py:DerivedClass.process
          - derived.py:DerivedClass CONTAINS derived.py:DerivedClass.process
          - derived.py:DerivedClass EXTENDS base.py:BaseClass
          - derived.py IMPORTS base.py  (DerivedClass references BaseClass)
        """
        base_rel = "src/base.py"
        derived_rel = "src/derived.py"
        tags = {
            base_rel: [
                _make_tag(rel_fname=base_rel, fname=f"/repo/{base_rel}",
                          name="BaseClass", ident="BaseClass",
                          kind="def", type="class", line=0, end_line=10),
            ],
            derived_rel: [
                _make_tag(rel_fname=derived_rel, fname=f"/repo/{derived_rel}",
                          name="DerivedClass", ident="DerivedClass",
                          kind="def", type="class", line=0, end_line=20,
                          base=["BaseClass"]),
                _make_tag(rel_fname=derived_rel, fname=f"/repo/{derived_rel}",
                          name="process", ident="process",
                          kind="def", type="method", line=5, end_line=10),
                # Reference from within DerivedClass to BaseClass
                _make_tag(rel_fname=derived_rel, fname=f"/repo/{derived_rel}",
                          name="BaseClass", ident="BaseClass",
                          kind="ref", type="class", line=2, end_line=2),
            ],
        }
        G = _run_create_graph(tags, {base_rel: "", derived_rel: ""})

        edge_types = {d["type"] for _, _, d in G.edges(data=True)}
        assert "CONTAINS" in edge_types, "CONTAINS edges expected"
        assert "EXTENDS" in edge_types, "EXTENDS edge expected"
        assert "IMPORTS" in edge_types, "IMPORTS edge expected"

        # EXTENDS: DerivedClass → BaseClass
        extends = [(u, v) for u, v, d in G.edges(data=True)
                   if d.get("type") == "EXTENDS"]
        assert (f"{derived_rel}:DerivedClass", f"{base_rel}:BaseClass") in extends

        # CONTAINS: class → method
        contains = [(u, v) for u, v, d in G.edges(data=True)
                    if d.get("type") == "CONTAINS"]
        assert (f"{derived_rel}:DerivedClass", f"{derived_rel}:DerivedClass.process") in contains

        # IMPORTS: derived.py → base.py
        imports = [(u, v) for u, v, d in G.edges(data=True)
                   if d.get("type") == "IMPORTS"]
        assert (derived_rel, base_rel) in imports

    def test_file_nodes_created_for_all_files(self):
        """Every processed file must have a FILE node in the graph."""
        files = {"src/a.py", "src/b.py", "src/c.py"}
        tags = {
            f: [_make_tag(rel_fname=f, fname=f"/repo/{f}",
                          name="func", ident="func", kind="def", type="function",
                          line=0, end_line=3)]
            for f in files
        }
        G = _run_create_graph(tags, {f: "" for f in files})

        file_nodes = {n for n, d in G.nodes(data=True) if d.get("type") == "FILE"}
        assert files == file_nodes
