"""
Unit tests for the three deepeval-ported metrics in qna_evaluator.py:

  1. ContextualPrecision  — _calculate_contextual_precision() (MAP formula)
                            QnAEvaluator._score_contextual_precision()
                            QnAEvaluator._evaluate_dataset_per_case()
  2. ContextualRecall     — QnAEvaluator._score_contextual_recall()
  3. ContextualRelevancy  — QnAEvaluator._score_contextual_relevancy()
  4. QnAEvaluator         — _evaluate_single() end-to-end with all 5 metrics
                            _aggregate()  aggregation correctness
  5. Shared runners       — _run_rubrics(), _evaluate_dataset()
  6. Context normalisation — _extract_text_from_chunk(), _normalize_retrieval_context()

All pydantic_evals Dataset.evaluate calls are mocked via the evaluator's
``_evaluate_dataset`` / ``_evaluate_dataset_per_case`` helpers so no network
access is required.

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path: put the evaluators directory first so it wins over the
# 'qna-evaluator' package directory that pytest discovers in tests/unit-tests/.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parents[3].resolve()
_EVALUATORS_PATH = (
    _REPO_ROOT
    / ".kiro/skills/potpie-evaluator/scripts/deepeval-scoring/evaluators"
)
_EVALUATORS_PARENT = _EVALUATORS_PATH.parent  # deepeval-scoring/

# Drop any stale cached import before re-importing
for _bad in list(sys.modules.keys()):
    if _bad == "qna_evaluator":
        del sys.modules[_bad]

for _p in [str(_REPO_ROOT), str(_EVALUATORS_PARENT), str(_EVALUATORS_PATH)]:
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_EVALUATORS_PATH))
for _p in [str(_EVALUATORS_PARENT), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.append(_p)

import importlib  # noqa: E402
_mod = importlib.import_module("qna_evaluator")


# ===========================================================================
# Helpers
# ===========================================================================

def _make_evaluator():
    """Return a QnAEvaluator bypassing _build_judge_model (stubbed by conftest)."""
    ev = object.__new__(_mod.QnAEvaluator)
    ev._judge_model = MagicMock(name="judge_model")
    return ev


# ===========================================================================
# 1. _calculate_contextual_precision  (pure Python, no LLM)
# ===========================================================================

class TestCalculateContextualPrecision:
    """Unit tests for the MAP-like scoring formula (accepts List[bool])."""

    def test_all_relevant_returns_one(self):
        assert _mod._calculate_contextual_precision([True, True, True]) == pytest.approx(1.0)

    def test_all_irrelevant_returns_zero(self):
        assert _mod._calculate_contextual_precision([False, False, False]) == pytest.approx(0.0)

    def test_empty_list_returns_zero(self):
        assert _mod._calculate_contextual_precision([]) == pytest.approx(0.0)

    def test_first_relevant_second_not(self):
        # k=1 pass → P@1 = 1/1 = 1.0; MAP = 1.0
        assert _mod._calculate_contextual_precision([True, False]) == pytest.approx(1.0)

    def test_first_irrelevant_second_relevant(self):
        # k=1 fail; k=2 pass → P@2 = 1/2; MAP = 0.5
        assert _mod._calculate_contextual_precision([False, True]) == pytest.approx(0.5)

    def test_three_nodes_two_relevant_at_1_and_3(self):
        # MAP = (1/1 + 2/3) / 2
        result = _mod._calculate_contextual_precision([True, False, True])
        assert result == pytest.approx((1.0 + 2 / 3) / 2, rel=1e-4)

    def test_three_nodes_two_relevant_at_2_and_3(self):
        # MAP = (1/2 + 2/3) / 2
        result = _mod._calculate_contextual_precision([False, True, True])
        assert result == pytest.approx((0.5 + 2 / 3) / 2, rel=1e-4)


# ===========================================================================
# 2. QnAEvaluator._score_contextual_precision  (_evaluate_dataset_per_case mocked)
# ===========================================================================

class TestScoreContextualPrecision:

    @pytest.mark.asyncio
    async def test_all_nodes_relevant(self):
        ev = _make_evaluator()
        ev._evaluate_dataset_per_case = AsyncMock(return_value=[True, True])
        score = await ev._score_contextual_precision("Q", "A", ["c1", "c2"])
        assert score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_no_nodes_relevant(self):
        ev = _make_evaluator()
        ev._evaluate_dataset_per_case = AsyncMock(return_value=[False, False])
        score = await ev._score_contextual_precision("Q", "A", ["c1", "c2"])
        assert score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_relevant_first_scores_higher_than_relevant_last(self):
        ev = _make_evaluator()
        ev._evaluate_dataset_per_case = AsyncMock(return_value=[True, False])
        score_first = await ev._score_contextual_precision("Q", "A", ["r", "i"])
        ev._evaluate_dataset_per_case = AsyncMock(return_value=[False, True])
        score_last = await ev._score_contextual_precision("Q", "A", ["i", "r"])
        assert score_first > score_last

    @pytest.mark.asyncio
    async def test_one_case_per_context_node(self):
        """Exactly one Case is built per context node."""
        ev = _make_evaluator()
        captured = []

        async def _capture(cases, task_outputs):
            captured.extend(cases)
            return [True] * len(cases)

        ev._evaluate_dataset_per_case = _capture
        await ev._score_contextual_precision("Q", "A", ["n1", "n2", "n3"])
        assert len(captured) == 3

    @pytest.mark.asyncio
    async def test_task_outputs_match_context_nodes(self):
        """task_outputs passed to _evaluate_dataset_per_case equal the context nodes."""
        ev = _make_evaluator()
        captured_outputs = []

        async def _capture(cases, task_outputs):
            captured_outputs.extend(task_outputs)
            return [False] * len(cases)

        ev._evaluate_dataset_per_case = _capture
        nodes = ["alpha", "beta", "gamma"]
        await ev._score_contextual_precision("Q", "A", nodes)
        assert captured_outputs == nodes


# ===========================================================================
# 3. QnAEvaluator._score_contextual_recall  (_evaluate_dataset mocked)
# ===========================================================================

class TestScoreContextualRecall:

    @pytest.mark.asyncio
    async def test_all_sentences_recalled(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(return_value=1.0)
        score = await ev._score_contextual_recall("Sentence one. Sentence two.", ["ctx"])
        assert score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_no_sentences_recalled(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(return_value=0.0)
        score = await ev._score_contextual_recall("A. B.", ["ctx"])
        assert score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_expected_output_returns_zero(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(side_effect=AssertionError("should not be called"))
        assert await ev._score_contextual_recall("", ["ctx"]) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_one_case_per_sentence(self):
        ev = _make_evaluator()
        captured = []

        async def _capture(cases, task_output):
            captured.extend(cases)
            return 1.0

        ev._evaluate_dataset = _capture
        await ev._score_contextual_recall(
            "First sentence. Second sentence. Third sentence.", ["ctx"]
        )
        assert len(captured) == 3

    @pytest.mark.asyncio
    async def test_context_capped_at_ten_chunks(self):
        ev = _make_evaluator()
        received = []

        async def _capture(cases, task_output):
            for case in cases:
                received.append(case.inputs.context)
            return 1.0

        ev._evaluate_dataset = _capture
        await ev._score_contextual_recall(
            "Only sentence.",
            [f"chunk_{i}" for i in range(15)],
        )
        for ctx in received:
            assert "chunk_10" not in ctx


# ===========================================================================
# 4. QnAEvaluator._score_contextual_relevancy  (_evaluate_dataset mocked)
# ===========================================================================

class TestScoreContextualRelevancy:

    @pytest.mark.asyncio
    async def test_fully_relevant(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(return_value=1.0)
        assert await ev._score_contextual_relevancy("Q", ["ctx"]) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_fully_irrelevant(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(return_value=0.0)
        assert await ev._score_contextual_relevancy("Q", ["ctx"]) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_context_returns_zero(self):
        ev = _make_evaluator()
        ev._evaluate_dataset = AsyncMock(side_effect=AssertionError("should not be called"))
        assert await ev._score_contextual_relevancy("Q", []) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_one_case_per_chunk(self):
        ev = _make_evaluator()
        captured = []

        async def _capture(cases, task_output):
            captured.extend(cases)
            return 0.5

        ev._evaluate_dataset = _capture
        await ev._score_contextual_relevancy("Q", ["a", "b", "c"])
        assert len(captured) == 3

    @pytest.mark.asyncio
    async def test_capped_at_ten_chunks(self):
        ev = _make_evaluator()
        captured = []

        async def _capture(cases, task_output):
            captured.extend(cases)
            return 1.0

        ev._evaluate_dataset = _capture
        await ev._score_contextual_relevancy("Q", [f"c{i}" for i in range(15)])
        assert len(captured) == 10


# ===========================================================================
# 5. QnAEvaluator._evaluate_single — end-to-end routing
# ===========================================================================

class TestQnAEvaluatorEvaluateSingle:

    @pytest.mark.asyncio
    async def test_only_answer_relevancy_when_no_context(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=0.8)

        result = await ev._evaluate_single({"question": "Q", "answer": "A"})

        assert set(result["metrics"].keys()) == {"AnswerRelevancy"}
        assert result["overall_score"] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_faithfulness_and_relevancy_added_with_context(self):
        """All 5 metrics run when context is present — Precision/Recall fall back to answer."""
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=1.0)
        ev._score_contextual_relevancy = AsyncMock(return_value=0.9)
        ev._score_contextual_precision = AsyncMock(return_value=0.8)
        ev._score_contextual_recall = AsyncMock(return_value=0.7)

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A", "retrieval_context": ["ctx"],
        })

        assert "Faithfulness" in result["metrics"]
        assert "ContextualRelevancy" in result["metrics"]
        # Precision and Recall now always run when context is present (fall back to answer)
        assert "ContextualPrecision" in result["metrics"]
        assert "ContextualRecall" in result["metrics"]
        # Verify the fallback: _score_contextual_precision was called with answer as expected_output
        ev._score_contextual_precision.assert_called_once_with("Q", "A", ["ctx"])

    @pytest.mark.asyncio
    async def test_all_five_metrics_with_context_and_expected_output(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=1.0)
        ev._score_contextual_relevancy = AsyncMock(return_value=0.8)
        ev._score_contextual_precision = AsyncMock(return_value=0.7)
        ev._score_contextual_recall = AsyncMock(return_value=0.6)

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A",
            "retrieval_context": ["ctx"], "expected_output": "E.",
        })

        assert set(result["metrics"].keys()) == {
            "AnswerRelevancy", "Faithfulness",
            "ContextualRelevancy", "ContextualPrecision", "ContextualRecall",
        }

    @pytest.mark.asyncio
    async def test_golden_answer_alias(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=1.0)
        ev._score_contextual_relevancy = AsyncMock(return_value=1.0)
        ev._score_contextual_precision = AsyncMock(return_value=1.0)
        ev._score_contextual_recall = AsyncMock(return_value=1.0)

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A",
            "retrieval_context": ["ctx"], "golden_answer": "Golden.",
        })

        assert "ContextualPrecision" in result["metrics"]
        assert "ContextualRecall" in result["metrics"]

    @pytest.mark.asyncio
    async def test_metric_failure_scores_zero_and_continues(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=0.9)
        ev._score_contextual_relevancy = AsyncMock(side_effect=RuntimeError("down"))
        ev._score_contextual_precision = AsyncMock(side_effect=RuntimeError("down"))
        ev._score_contextual_recall = AsyncMock(side_effect=RuntimeError("down"))

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A",
            "retrieval_context": ["ctx"], "expected_output": "E.",
        })

        assert result["metrics"]["ContextualRelevancy"]["score"] == pytest.approx(0.0)
        assert result["metrics"]["ContextualPrecision"]["score"] == pytest.approx(0.0)
        assert result["metrics"]["ContextualRecall"]["score"] == pytest.approx(0.0)
        assert result["metrics"]["AnswerRelevancy"]["score"] == pytest.approx(0.9)
        assert result["metrics"]["Faithfulness"]["score"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_overall_score_is_mean_of_metric_scores(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=0.8)
        ev._score_contextual_relevancy = AsyncMock(return_value=0.6)
        ev._score_contextual_precision = AsyncMock(return_value=0.4)
        ev._score_contextual_recall = AsyncMock(return_value=1.0)

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A",
            "retrieval_context": ["ctx"], "expected_output": "E.",
        })

        scores = [v["score"] for v in result["metrics"].values()]
        assert result["overall_score"] == pytest.approx(sum(scores) / len(scores), rel=1e-4)

    @pytest.mark.asyncio
    async def test_success_flag_threshold(self):
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=1.0)
        ev._score_contextual_relevancy = AsyncMock(return_value=0.3)

        result = await ev._evaluate_single({
            "question": "Q", "answer": "A", "retrieval_context": ["ctx"],
        })

        assert result["metrics"]["AnswerRelevancy"]["success"] is True
        assert result["metrics"]["ContextualRelevancy"]["success"] is False


# ===========================================================================
# 6. QnAEvaluator._aggregate
# ===========================================================================

class TestQnAEvaluatorAggregate:

    def test_empty_input(self):
        ev = _make_evaluator()
        assert ev._aggregate([]) == {
            "overall_score": 0.0, "cases": [],
            "metrics_summary": {}, "total_cases": 0, "passed_cases": 0,
        }

    def test_single_passing_case(self):
        ev = _make_evaluator()
        result = ev._aggregate([{
            "overall_score": 0.8, "question": "Q", "answer": "A",
            "retrieval_context": [],
            "metrics": {"AnswerRelevancy": {"score": 0.8}},
        }])
        assert result["total_cases"] == 1
        assert result["passed_cases"] == 1
        assert result["metrics_summary"]["AnswerRelevancy"] == pytest.approx(0.8)

    def test_single_failing_case(self):
        ev = _make_evaluator()
        result = ev._aggregate([{
            "overall_score": 0.3, "question": "Q", "answer": "A",
            "retrieval_context": [],
            "metrics": {"AnswerRelevancy": {"score": 0.3}},
        }])
        assert result["passed_cases"] == 0

    def test_metrics_summary_averaged_across_cases(self):
        ev = _make_evaluator()
        result = ev._aggregate([
            {"overall_score": 1.0, "question": "Q1", "answer": "A",
             "retrieval_context": [],
             "metrics": {"AnswerRelevancy": {"score": 1.0}, "ContextualRelevancy": {"score": 0.6}}},
            {"overall_score": 0.5, "question": "Q2", "answer": "A",
             "retrieval_context": [],
             "metrics": {"AnswerRelevancy": {"score": 0.4}, "ContextualRelevancy": {"score": 0.8}}},
        ])
        assert result["metrics_summary"]["AnswerRelevancy"] == pytest.approx(0.7)
        assert result["metrics_summary"]["ContextualRelevancy"] == pytest.approx(0.7)

    def test_overall_score_mean_of_metric_averages(self):
        ev = _make_evaluator()
        scores = [0.6, 0.8, 1.0, 0.5, 0.7]
        result = ev._aggregate([{
            "overall_score": 0.6, "question": "Q", "answer": "A",
            "retrieval_context": [],
            "metrics": {
                "AnswerRelevancy":     {"score": scores[0]},
                "Faithfulness":        {"score": scores[1]},
                "ContextualRelevancy": {"score": scores[2]},
                "ContextualPrecision": {"score": scores[3]},
                "ContextualRecall":    {"score": scores[4]},
            },
        }])
        assert result["overall_score"] == pytest.approx(sum(scores) / len(scores), rel=1e-4)

    def test_passed_cases_threshold(self):
        ev = _make_evaluator()
        result = ev._aggregate([
            {"overall_score": 0.5,  "question": "Q1", "answer": "A", "retrieval_context": [], "metrics": {}},
            {"overall_score": 0.49, "question": "Q2", "answer": "A", "retrieval_context": [], "metrics": {}},
            {"overall_score": 1.0,  "question": "Q3", "answer": "A", "retrieval_context": [], "metrics": {}},
        ])
        assert result["passed_cases"] == 2
        assert result["total_cases"] == 3

    def test_metric_present_only_in_some_cases(self):
        ev = _make_evaluator()
        result = ev._aggregate([
            {"overall_score": 0.8, "question": "Q1", "answer": "A",
             "retrieval_context": [],
             "metrics": {"AnswerRelevancy": {"score": 0.7}, "ContextualPrecision": {"score": 0.9}}},
            {"overall_score": 0.6, "question": "Q2", "answer": "A",
             "retrieval_context": [],
             "metrics": {"AnswerRelevancy": {"score": 0.6}}},
        ])
        assert result["metrics_summary"]["AnswerRelevancy"] == pytest.approx(0.65)
        assert result["metrics_summary"]["ContextualPrecision"] == pytest.approx(0.9)


# ===========================================================================
# 7. _extract_text_from_chunk  and  _normalize_retrieval_context
# ===========================================================================

class TestExtractTextFromChunk:

    def test_plain_string_returned_as_is(self):
        assert _mod._extract_text_from_chunk("Hello world") == "Hello world"

    def test_empty_string_returns_none(self):
        assert _mod._extract_text_from_chunk("") is None

    def test_empty_json_list_returns_none(self):
        assert _mod._extract_text_from_chunk("[[]]") is None
        assert _mod._extract_text_from_chunk("[]") is None

    def test_agent_dict_with_text_field(self):
        import json
        chunk = json.dumps([{"file_path": "foo.py", "docstring": "A doc", "text": "actual code"}])
        result = _mod._extract_text_from_chunk(chunk)
        assert result == "actual code"

    def test_agent_dict_prefers_text_over_docstring(self):
        import json
        chunk = json.dumps([{"docstring": "A doc", "text": "code body"}])
        assert _mod._extract_text_from_chunk(chunk) == "code body"

    def test_agent_dict_falls_back_to_docstring_when_no_text(self):
        import json
        chunk = json.dumps([{"file_path": "foo.py", "docstring": "Only a docstring"}])
        result = _mod._extract_text_from_chunk(chunk)
        assert result == "Only a docstring"

    def test_agent_dict_falls_back_to_content(self):
        import json
        chunk = json.dumps({"success": True, "content": "file content here"})
        result = _mod._extract_text_from_chunk(chunk)
        assert result == "file content here"

    def test_error_dict_with_no_content_returns_none(self):
        import json
        chunk = json.dumps({"success": False, "error": "Too big", "content": None})
        assert _mod._extract_text_from_chunk(chunk) is None

    def test_multiple_items_joined(self):
        import json
        chunk = json.dumps([{"text": "first"}, {"text": "second"}])
        result = _mod._extract_text_from_chunk(chunk)
        assert "first" in result
        assert "second" in result

    def test_non_string_input_coerced(self):
        # A bare integer stringifies to "42", which JSON-parses as an int scalar —
        # not a dict/list, so there's no text to extract; returns None.
        assert _mod._extract_text_from_chunk(42) is None

    def test_python_literal_list_single_quotes_extracts_text(self):
        # repr() of a list of dicts uses single quotes — json.loads fails,
        # ast.literal_eval should succeed and extract the text field.
        chunk = "[{'file_path': 'foo.py', 'docstring': 'A doc', 'text': 'actual code'}]"
        assert _mod._extract_text_from_chunk(chunk) == "actual code"

    def test_python_literal_dict_single_quotes_extracts_content(self):
        # repr() of a plain dict with a content field.
        chunk = "{'success': True, 'content': 'file content here'}"
        assert _mod._extract_text_from_chunk(chunk) == "file content here"

    def test_python_literal_empty_list_returns_none(self):
        # ast.literal_eval succeeds but yields an empty list → no text.
        assert _mod._extract_text_from_chunk("[]") is None

    def test_python_literal_no_known_field_returns_none(self):
        # Dict with no text/content/docstring field → nothing to extract.
        chunk = "{'file_path': 'x.py', 'start_line': 1}"
        assert _mod._extract_text_from_chunk(chunk) is None


class TestNormalizeRetrievalContext:

    def test_plain_strings_pass_through(self):
        ctx = ["chunk one", "chunk two"]
        assert _mod._normalize_retrieval_context(ctx) == ["chunk one", "chunk two"]

    def test_empty_list_returns_empty(self):
        assert _mod._normalize_retrieval_context([]) == []

    def test_filters_out_empty_json_chunks(self):
        ctx = ["[[]]", "real text", "[]"]
        result = _mod._normalize_retrieval_context(ctx)
        assert result == ["real text"]

    def test_extracts_text_from_agent_dicts(self):
        import json
        chunk = json.dumps([{"file_path": "f.py", "text": "def foo(): pass"}])
        result = _mod._normalize_retrieval_context([chunk])
        assert result == ["def foo(): pass"]

    def test_filters_error_chunks_with_null_content(self):
        import json
        good = "readable text"
        bad = json.dumps({"success": False, "error": "oops", "content": None})
        result = _mod._normalize_retrieval_context([good, bad])
        assert result == ["readable text"]

    def test_normalize_called_in_evaluate_single(self):
        """_evaluate_single must normalise retrieval_context before scoring AND
        return the normalised context so the report matches what metrics saw."""
        import asyncio, json
        ev = _make_evaluator()
        ev._run_rubrics = AsyncMock(return_value=1.0)
        ev._score_contextual_relevancy = AsyncMock(return_value=0.5)

        bad_chunk = json.dumps({"success": False, "error": "oops", "content": None})
        good_chunk = "some real context"

        result = asyncio.run(ev._evaluate_single({
            "question": "Q", "answer": "A",
            "retrieval_context": [bad_chunk, good_chunk],
        }))

        # Scoring used the normalised context (bad chunk filtered out)
        ev._score_contextual_relevancy.assert_called_once()
        called_ctx = ev._score_contextual_relevancy.call_args[0][1]
        assert bad_chunk not in called_ctx
        assert good_chunk in called_ctx

        # The returned result must carry the same normalised context, not the raw one
        assert "retrieval_context" in result
        assert bad_chunk not in result["retrieval_context"]
        assert good_chunk in result["retrieval_context"]

    def test_python_query_response_repr_returns_none(self):
        chunk = "[[QueryResponse(node_id='abc', docstring='...', file_path='x.py', start_line=1, end_line=5, similarity=0.76)], []]"
        assert _mod._extract_text_from_chunk(chunk) is None

    def test_directory_listing_passes_through_as_prose(self):
        chunk = ".deepwiki/\n  10_Object_Model.md\n  11_Templates.md\n"
        result = _mod._extract_text_from_chunk(chunk)
        assert result is not None
        assert "10_Object_Model.md" in result
