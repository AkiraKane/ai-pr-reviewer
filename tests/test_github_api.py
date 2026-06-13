"""Tests for GitHub API inline review posting."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from agent import InlineComment
from github_api import (
    ReviewResult,
    get_repo_owner_name,
    post_inline_review,
    _format_comment_body,
    _generate_review_body,
)


# ---------------------------------------------------------------------------
# _format_comment_body
# ---------------------------------------------------------------------------

class TestFormatCommentBody:
    def test_critical(self):
        c = InlineComment("a.py", 1, 5, "critical", "Null dereference.")
        body = _format_comment_body(c)
        assert "[CRITICAL]" in body
        assert "Null dereference." in body

    def test_important(self):
        c = InlineComment("a.py", 1, 5, "important", "Missing input validation.")
        body = _format_comment_body(c)
        assert "[IMPORTANT]" in body

    def test_suggestion(self):
        c = InlineComment("a.py", 1, 5, "suggestion", "Consider using a helper.")
        body = _format_comment_body(c)
        assert "[SUGGESTION]" in body

    def test_unknown_severity(self):
        c = InlineComment("a.py", 1, 5, "unknown", "Some note.")
        body = _format_comment_body(c)
        assert "[NOTE]" in body


# ---------------------------------------------------------------------------
# _generate_review_body
# ---------------------------------------------------------------------------

class TestGenerateReviewBody:
    def test_mixed_severities(self):
        comments = [
            InlineComment("a.py", 1, 1, "critical", "Bug"),
            InlineComment("a.py", 2, 2, "important", "Should fix"),
            InlineComment("b.py", 1, 1, "suggestion", "Nice to have"),
        ]
        body = _generate_review_body(comments)
        assert "Critical:" in body
        assert "Important:" in body
        assert "Suggestion:" in body
        assert "Total: 3 comment(s)" in body

    def test_only_suggestions(self):
        comments = [
            InlineComment("a.py", 1, 1, "suggestion", "Rename var"),
            InlineComment("a.py", 2, 2, "suggestion", "Add comment"),
        ]
        body = _generate_review_body(comments)
        assert "Critical:" not in body
        assert "2 improvement(s)" in body

    def test_empty_comments(self):
        body = _generate_review_body([])
        assert "Total: 0 comment(s)" in body


# ---------------------------------------------------------------------------
# get_repo_owner_name
# ---------------------------------------------------------------------------

class TestGetRepoOwnerName:
    @patch("github_api.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"owner": {"login": "akira"}, "name": "ai-pr-reviewer"}',
        )
        owner, name = get_repo_owner_name("/some/path")
        assert owner == "akira"
        assert name == "ai-pr-reviewer"

    @patch("github_api.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="not a repo")
        with pytest.raises(RuntimeError, match="Failed to get repo info"):
            get_repo_owner_name("/bad/path")


# ---------------------------------------------------------------------------
# post_inline_review
# ---------------------------------------------------------------------------

class TestPostInlineReview:
    @patch("github_api.get_repo_owner_name")
    @patch("github_api.subprocess.run")
    def test_success(self, mock_run, mock_repo):
        mock_repo.return_value = ("akira", "ai-pr-reviewer")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"html_url": "https://github.com/akira/ai-pr-reviewer/pull/5#pullrequestreview-123"}',
        )

        comments = [
            InlineComment("src/main.py", 10, 15, "critical", "Fix this."),
            InlineComment("src/main.py", 20, 25, "suggestion", "Nice to have."),
        ]

        result = post_inline_review(
            pr_number=5,
            comments=comments,
            body="Review complete.",
            repo_path="/repo",
        )

        assert result.success is True
        assert "pullrequestreview-123" in result.review_url

        # Verify gh api was called correctly
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "gh" in cmd
        assert "api" in cmd
        assert "--method" in cmd
        assert "POST" in cmd
        assert "repos/akira/ai-pr-reviewer/pulls/5/reviews" in cmd

    @patch("github_api.get_repo_owner_name")
    @patch("github_api.subprocess.run")
    def test_failure(self, mock_run, mock_repo):
        mock_repo.return_value = ("akira", "ai-pr-reviewer")
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Not Found",
        )

        result = post_inline_review(
            pr_number=999,
            comments=[InlineComment("a.py", 1, 1, "critical", "Bug")],
            repo_path="/repo",
        )

        assert result.success is False
        assert "Not Found" in result.error

    @patch("github_api.get_repo_owner_name")
    @patch("github_api.subprocess.run")
    def test_payload_format(self, mock_run, mock_repo):
        """Verify the JSON payload sent to gh api has the correct structure."""
        mock_repo.return_value = ("owner", "repo")
        mock_run.return_value = MagicMock(returncode=0, stdout='{}')

        comments = [
            InlineComment("a.py", 5, 10, "critical", "Bug here."),
        ]

        post_inline_review(pr_number=1, comments=comments, repo_path="/repo")

        # The input is passed via stdin to gh api
        call_kwargs = mock_run.call_args
        import json
        payload = json.loads(call_kwargs[1].get("input", call_kwargs[0][0] if len(call_kwargs[0]) > 1 else "{}"))
        if "input" not in call_kwargs[1]:
            # Check positional args
            for arg in call_kwargs[0]:
                if isinstance(arg, str) and arg.startswith("{"):
                    payload = json.loads(arg)
                    break

        # Verify structure exists
        assert "body" in payload
        assert "event" in payload
        assert "comments" in payload
        assert payload["event"] == "COMMENT"
        assert len(payload["comments"]) == 1
        assert payload["comments"][0]["path"] == "a.py"
        assert payload["comments"][0]["position"] == 5
        assert "[CRITICAL]" in payload["comments"][0]["body"]
