"""Tests for the multi-file review agent."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from diff_parser import FileChange, PRDiff
from agent import (
    InlineComment,
    AgentReview,
    run_agent_review,
    _parse_inline_comments,
    _parse_cross_file_comments,
    _extract_json,
    _map_line_to_position,
)


# ---------------------------------------------------------------------------
# InlineComment
# ---------------------------------------------------------------------------

class TestInlineComment:
    def test_to_github_payload(self):
        c = InlineComment(
            path="src/main.py",
            position=5,
            line=10,
            severity="critical",
            body="Null dereference here.",
        )
        payload = c.to_github_payload()
        assert payload == {
            "path": "src/main.py",
            "position": 5,
            "body": "Null dereference here.",
        }


# ---------------------------------------------------------------------------
# AgentReview
# ---------------------------------------------------------------------------

class TestAgentReview:
    def test_empty_review(self):
        review = AgentReview()
        assert review.all_comments == []
        assert review.critical_count == 0
        assert review.has_critical is False

    def test_critical_count(self):
        review = AgentReview(
            comments=[
                InlineComment("a.py", 1, 1, "critical", "bug"),
                InlineComment("a.py", 2, 2, "suggestion", "style"),
            ],
            cross_file_comments=[
                InlineComment("b.py", 1, 1, "critical", "mismatch"),
            ],
        )
        assert review.critical_count == 2
        assert review.has_critical is True
        assert len(review.all_comments) == 3

    def test_to_markdown(self):
        review = AgentReview(
            summary="Overall review summary.",
            comments=[
                InlineComment("a.py", 1, 10, "critical", "Fix this bug."),
                InlineComment("a.py", 2, 20, "suggestion", "Consider refactoring."),
            ],
        )
        md = review.to_markdown()
        assert "Overall review summary." in md
        assert "`a.py`" in md
        assert "CRITICAL" in md
        assert "SUGGESTION" in md
        assert "line 10" in md
        assert "line 20" in md

    def test_to_json_dict(self):
        review = AgentReview(
            summary="Summary",
            comments=[InlineComment("a.py", 1, 5, "important", "Check this.")],
            cross_file_comments=[InlineComment("b.py", 3, 10, "critical", "Mismatch.")],
        )
        d = review.to_json_dict()
        assert d["summary"] == "Summary"
        assert len(d["comments"]) == 1
        assert len(d["cross_file_comments"]) == 1
        assert d["critical_count"] == 1
        assert d["comments"][0]["path"] == "a.py"
        assert d["cross_file_comments"][0]["line"] == 10

    def test_markdown_grouped_by_file(self):
        review = AgentReview(
            comments=[
                InlineComment("a.py", 1, 5, "suggestion", "Use context manager."),
                InlineComment("b.py", 1, 3, "critical", "Off-by-one."),
            ],
        )
        md = review.to_markdown()
        assert "`a.py`" in md
        assert "`b.py`" in md


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        text = '{"comments": []}'
        assert _extract_json(text) == '{"comments": []}'

    def test_json_in_code_block(self):
        text = 'Here is the result:\n```json\n{"comments": [{"line": 1, "severity": "critical", "body": "test"}]}\n```\nDone.'
        result = _extract_json(text)
        assert result is not None
        assert '"comments"' in result

    def test_json_with_surrounding_text(self):
        text = 'I reviewed the code.\n{"comments": [{"line": 10, "severity": "suggestion", "body": "nice"}]}\nOverall good.'
        result = _extract_json(text)
        assert result is not None
        assert '"line": 10' in result

    def test_no_json(self):
        assert _extract_json("No issues found, looks good.") is None

    def test_nested_json(self):
        text = 'Data: {"a": {"b": 1}, "c": [1, 2]} end'
        result = _extract_json(text)
        assert result == '{"a": {"b": 1}, "c": [1, 2]}'


# ---------------------------------------------------------------------------
# _map_line_to_position
# ---------------------------------------------------------------------------

class TestMapLineToPosition:
    def test_simple_diff(self):
        diff = (
            "diff --git a/test.py b/test.py\n"
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,5 +1,6 @@\n"
            " line1\n"
            " line2\n"
            "+added line\n"
            " line3\n"
            " line4\n"
            " line5\n"
        )
        # New line 3 is "added line" (the + line), which is at diff position 6
        pos = _map_line_to_position(diff, 3)
        assert pos >= 1

    def test_default_on_failure(self):
        diff = "diff --git a/x.py b/x.py\n@@ -0,0 +1 @@\n+line\n"
        # Requesting line 999 which doesn't exist
        pos = _map_line_to_position(diff, 999)
        assert pos == 1


# ---------------------------------------------------------------------------
# _parse_inline_comments
# ---------------------------------------------------------------------------

class TestParseInlineComments:
    def test_valid_json(self):
        raw = '{"comments": [{"line": 5, "severity": "critical", "body": "Bug here"}]}'
        fc = FileChange(
            path="test.py",
            status="modified",
            diff="@@ -1,10 +1,10 @@\n line\n" * 10,
        )
        comments = _parse_inline_comments(raw, fc)
        assert len(comments) == 1
        assert comments[0].path == "test.py"
        assert comments[0].line == 5
        assert comments[0].severity == "critical"
        assert comments[0].body == "Bug here"

    def test_empty_comments(self):
        raw = '{"comments": []}'
        fc = FileChange(path="test.py", status="modified", diff="")
        comments = _parse_inline_comments(raw, fc)
        assert comments == []

    def test_invalid_json(self):
        raw = "This is not JSON at all."
        fc = FileChange(path="test.py", status="modified", diff="")
        comments = _parse_inline_comments(raw, fc)
        assert comments == []

    def test_json_in_code_block(self):
        raw = 'Review result:\n```json\n{"comments": [{"line": 3, "severity": "suggestion", "body": "Consider renaming"}]}\n```'
        fc = FileChange(path="utils.py", status="modified", diff="")
        comments = _parse_inline_comments(raw, fc)
        assert len(comments) == 1
        assert comments[0].path == "utils.py"
        assert comments[0].line == 3


# ---------------------------------------------------------------------------
# _parse_cross_file_comments
# ---------------------------------------------------------------------------

class TestParseCrossFileComments:
    def test_valid_cross_review(self):
        raw = '{"comments": [{"file": "interface.py", "line": 10, "severity": "critical", "body": "Method signature changed but implementation not updated"}], "summary": "Found 1 issue."}'
        files = [
            FileChange(path="interface.py", status="modified", diff="@@ -5,10 +5,10 @@\n" + "\n".join([" line"] * 10)),
            FileChange(path="impl.py", status="modified", diff=""),
        ]
        comments = _parse_cross_file_comments(raw, files)
        assert len(comments) == 1
        assert comments[0].path == "interface.py"
        assert comments[0].severity == "critical"

    def test_unknown_file_falls_back(self):
        raw = '{"comments": [{"file": "nonexistent.py", "line": 1, "severity": "important", "body": "Missing file"}], "summary": "test"}'
        files = [FileChange(path="real.py", status="modified", diff="")]
        comments = _parse_cross_file_comments(raw, files)
        assert len(comments) == 1
        assert comments[0].path == "real.py"  # Falls back to first file

    def test_empty_cross_review(self):
        raw = '{"comments": [], "summary": "No issues."}'
        comments = _parse_cross_file_comments(raw, [])
        assert comments == []


# ---------------------------------------------------------------------------
# run_agent_review (mocked LLM)
# ---------------------------------------------------------------------------

class TestRunAgentReview:
    @patch("agent.llm_module")
    def test_single_file_no_cross_review(self, mock_llm):
        mock_llm.review_file.return_value = '{"comments": [{"line": 1, "severity": "suggestion", "body": "Use type hints."}]}'

        pr = PRDiff(pr_number=1, title="Test PR", body="")
        pr.files = [FileChange(path="a.py", status="modified", additions=5, deletions=2, diff="@@ -1,3 +1,5 @@\n line\n+new\n")]

        review = run_agent_review(pr)

        # Should NOT call cross_review for a single-file PR
        mock_llm.cross_review.assert_not_called()
        assert len(review.comments) == 1
        assert review.comments[0].path == "a.py"

    @patch("agent.llm_module")
    def test_multi_file_with_cross_review(self, mock_llm):
        mock_llm.review_file.return_value = '{"comments": []}'
        mock_llm.cross_review.return_value = '{"comments": [{"file": "b.py", "line": 1, "severity": "critical", "body": "Missing test for new function."}], "summary": "1 cross-file issue found."}'

        pr = PRDiff(pr_number=2, title="Multi PR", body="")
        pr.files = [
            FileChange(path="a.py", status="modified", additions=3, deletions=0, diff="@@ -1,3 +1,6 @@\n line\n+new1\n+new2\n"),
            FileChange(path="b.py", status="modified", additions=5, deletions=1, diff="@@ -1,4 +1,8 @@\n line\n+new3\n"),
        ]

        review = run_agent_review(pr)

        # review_file called once per file
        assert mock_llm.review_file.call_count == 2
        # cross_review called once for multi-file
        mock_llm.cross_review.assert_called_once()
        assert len(review.cross_file_comments) == 1
        assert review.cross_file_comments[0].severity == "critical"
        assert review.has_critical

    @patch("agent.llm_module")
    def test_context_passed_between_files(self, mock_llm):
        mock_llm.review_file.return_value = '{"comments": []}'
        mock_llm.cross_review.return_value = '{"comments": [], "summary": "No cross-file issues."}'

        pr = PRDiff(pr_number=3, title="Context PR", body="")
        pr.files = [
            FileChange(path="a.py", status="modified", diff=""),
            FileChange(path="b.py", status="modified", diff=""),
        ]

        run_agent_review(pr)

        # First call should have empty context
        first_call = mock_llm.review_file.call_args_list[0]
        assert first_call[1]["context"] == ""

        # Second call should have non-empty context (from first file's review)
        second_call = mock_llm.review_file.call_args_list[1]
        ctx = second_call[1]["context"]
        # Context should reference the first file
        assert "a.py" in ctx

    @patch("agent.llm_module")
    def test_llm_returns_garbage(self, mock_llm):
        mock_llm.review_file.return_value = "I think the code is fine! No JSON here."
        mock_llm.cross_review.return_value = "Looks good overall."

        pr = PRDiff(pr_number=4, title="Bad LLM", body="")
        pr.files = [
            FileChange(path="a.py", status="modified", diff=""),
            FileChange(path="b.py", status="modified", diff=""),
        ]

        review = run_agent_review(pr)

        # Should gracefully handle non-JSON LLM output
        assert review.comments == []
        assert review.cross_file_comments == []
