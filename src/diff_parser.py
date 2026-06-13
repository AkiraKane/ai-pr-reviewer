"""Parse PR diffs into structured review data."""

import subprocess
from dataclasses import dataclass, field


@dataclass
class FileChange:
    """A single file change in a PR."""
    path: str
    status: str  # added, modified, deleted, renamed
    additions: int = 0
    deletions: int = 0
    diff: str = ""


@dataclass
class PRDiff:
    """Structured PR diff data."""
    pr_number: int
    title: str
    body: str
    files: list[FileChange] = field(default_factory=list)

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_prompt(self) -> str:
        """Convert to prompt for LLM review."""
        parts = [
            f"PR #{self.pr_number}: {self.title}",
            "",
        ]

        if self.body:
            parts.append(f"Description: {self.body[:500]}")
            parts.append("")

        parts.append(f"Files changed: {self.file_count}")
        parts.append(f"Additions: +{self.total_additions}, Deletions: -{self.total_deletions}")
        parts.append("")

        for f in self.files[:10]:  # Limit to 10 files for context window
            parts.append(f"--- {f.path} ({f.status}) ---")
            parts.append(f"Changes: +{f.additions} -{f.deletions}")
            # Include first 50 lines of diff
            diff_lines = f.diff.split("\n")[:50]
            parts.append("\n".join(diff_lines))
            if len(f.diff.split("\n")) > 50:
                parts.append(f"... ({len(f.diff.split(chr(10))) - 50} more lines)")
            parts.append("")

        if len(self.files) > 10:
            parts.append(f"... and {len(self.files) - 10} more files")

        return "\n".join(parts)


def get_pr_diff(pr_number: int, repo_path: str = ".") -> PRDiff:
    """Get diff for a GitHub PR using gh CLI."""
    # Get PR info
    pr_info = _run_gh(["pr", "view", str(pr_number),
                        "--json", "number,title,body"], repo_path)

    pr = PRDiff(
        pr_number=pr_number,
        title=pr_info.get("title", ""),
        body=pr_info.get("body", "") or "",
    )

    # Get changed files
    files_json = _run_gh(["pr", "diff", str(pr_number),
                           "--stat"], repo_path)

    # Get actual diff
    diff_result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number)],
        capture_output=True, text=True, cwd=repo_path
    )

    if diff_result.returncode != 0:
        return pr

    # Parse diff into file changes
    current_file = None
    current_diff = []
    additions = 0
    deletions = 0

    for line in diff_result.stdout.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file:
                current_file.diff = "\n".join(current_diff)
                current_file.additions = additions
                current_file.deletions = deletions
                pr.files.append(current_file)

            # Start new file
            parts = line.split(" b/")
            path = parts[-1] if len(parts) > 1 else "unknown"
            current_file = FileChange(path=path, status="modified")
            current_diff = [line]
            additions = 0
            deletions = 0
        elif current_file:
            current_diff.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

    # Save last file
    if current_file:
        current_file.diff = "\n".join(current_diff)
        current_file.additions = additions
        current_file.deletions = deletions
        pr.files.append(current_file)

    return pr


def get_unstaged_diff(repo_path: str = ".") -> str:
    """Get unstaged changes diff."""
    result = subprocess.run(
        ["git", "diff"],
        capture_output=True, text=True, cwd=repo_path
    )
    return result.stdout


def get_staged_diff(repo_path: str = ".") -> str:
    """Get staged changes diff."""
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True, text=True, cwd=repo_path
    )
    return result.stdout


def _run_gh(args: list[str], cwd: str = ".") -> dict:
    """Run gh CLI and return JSON output."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True, text=True, cwd=cwd
    )
    if result.returncode != 0:
        return {}
    try:
        import json
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
