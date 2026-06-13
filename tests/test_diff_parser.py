"""Tests for diff parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from diff_parser import FileChange, PRDiff


class TestFileChange:
    def test_defaults(self):
        fc = FileChange(path="test.py", status="modified")
        assert fc.additions == 0
        assert fc.deletions == 0
        assert fc.diff == ""


class TestPRDiff:
    def test_empty_pr(self):
        pr = PRDiff(pr_number=1, title="Test", body="")
        assert pr.file_count == 0
        assert pr.total_additions == 0
        assert pr.total_deletions == 0

    def test_with_files(self):
        pr = PRDiff(pr_number=1, title="Test", body="")
        pr.files = [
            FileChange(path="a.py", status="modified", additions=10, deletions=5),
            FileChange(path="b.py", status="added", additions=20, deletions=0),
        ]
        assert pr.file_count == 2
        assert pr.total_additions == 30
        assert pr.total_deletions == 5

    def test_to_prompt(self):
        pr = PRDiff(pr_number=42, title="Add feature", body="This adds a new feature")
        pr.files = [
            FileChange(
                path="feature.py",
                status="added",
                additions=15,
                deletions=0,
                diff="+def new_feature():\n+    pass"
            )
        ]
        prompt = pr.to_prompt()
        assert "PR #42" in prompt
        assert "Add feature" in prompt
        assert "feature.py" in prompt
        assert "+15" in prompt

    def test_to_prompt_limits_files(self):
        pr = PRDiff(pr_number=1, title="Big PR", body="")
        pr.files = [
            FileChange(path=f"file{i}.py", status="modified", additions=1, deletions=0)
            for i in range(20)
        ]
        prompt = pr.to_prompt()
        assert "and 10 more files" in prompt

    def test_to_prompt_truncates_body(self):
        pr = PRDiff(
            pr_number=1,
            title="Test",
            body="A" * 1000,
        )
        prompt = pr.to_prompt()
        assert len(prompt) < 2000  # Body should be truncated to 500 chars


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
