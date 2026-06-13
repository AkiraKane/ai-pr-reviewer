"""Multi-file reasoning agent for PR code review.

Reviews each changed file individually with cross-file awareness,
then performs a cross-file consistency analysis.
"""

from dataclasses import dataclass, field

from diff_parser import FileChange, PRDiff
import llm as llm_module


@dataclass
class InlineComment:
    """A single inline review comment tied to a diff position."""
    path: str
    position: int  # diff line position (1-indexed line in the diff hunk)
    line: int      # target file line number
    severity: str  # critical, important, suggestion
    body: str

    def to_github_payload(self) -> dict:
        """Format for GitHub API review comment."""
        return {
            "path": self.path,
            "position": self.position,
            "body": self.body,
        }


@dataclass
class AgentReview:
    """Structured output from the agent review loop."""
    comments: list[InlineComment] = field(default_factory=list)
    cross_file_comments: list[InlineComment] = field(default_factory=list)
    summary: str = ""

    @property
    def all_comments(self) -> list[InlineComment]:
        return self.comments + self.cross_file_comments

    @property
    def critical_count(self) -> int:
        return sum(
            1 for c in self.all_comments if c.severity == "critical"
        )

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    def to_markdown(self) -> str:
        """Render the full review as markdown."""
        parts = []

        if self.summary:
            parts.append(self.summary)
            parts.append("")

        # Group inline comments by file
        by_file: dict[str, list[InlineComment]] = {}
        for comment in self.all_comments:
            by_file.setdefault(comment.path, []).append(comment)

        for path, comments in by_file.items():
            parts.append(f"### `{path}`")
            parts.append("")
            for c in comments:
                icon = {"critical": "CRITICAL", "important": "IMPORTANT", "suggestion": "SUGGESTION"}.get(c.severity, "NOTE")
                parts.append(f"- **[{icon}]** (line {c.line}): {c.body}")
            parts.append("")

        # Cross-file section
        if self.cross_file_comments:
            parts.append("### Cross-file issues")
            parts.append("")
            for c in self.cross_file_comments:
                parts.append(f"- `{c.path}` (line {c.line}): {c.body}")
            parts.append("")

        return "\n".join(parts)

    def to_json_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "summary": self.summary,
            "comments": [
                {
                    "path": c.path,
                    "line": c.line,
                    "position": c.position,
                    "severity": c.severity,
                    "body": c.body,
                }
                for c in self.comments
            ],
            "cross_file_comments": [
                {
                    "path": c.path,
                    "line": c.line,
                    "position": c.position,
                    "severity": c.severity,
                    "body": c.body,
                }
                for c in self.cross_file_comments
            ],
            "critical_count": self.critical_count,
        }


def _map_line_to_position(diff_text: str, target_line: int) -> int:
    """Map a target file line number to the diff hunk position (1-indexed).

    Walks the diff lines and counts the position within the hunk that
    corresponds to the target file line.  Returns 1 as a safe default
    if the mapping fails.
    """
    current_new_line = 0
    position = 0

    for raw_line in diff_text.split("\n"):
        position += 1
        if raw_line.startswith("@@"):
            # Parse the --- +N,M @@ header to find new-file start line
            # Format: @@ -old,count +new,count @@
            try:
                plus_part = raw_line.split("+")[1].split(",")[0]
                current_new_line = int(plus_part)
            except (IndexError, ValueError):
                current_new_line = 0
            continue
        if raw_line.startswith("---") or raw_line.startswith("+++"):
            continue
        if raw_line.startswith("-"):
            # Deletion in old file -- doesn't advance new-file line
            continue
        if raw_line.startswith("+"):
            current_new_line += 1
        else:
            # Context line -- advances both old and new
            current_new_line += 1

        if current_new_line == target_line:
            return position

    return 1  # Fallback


def run_agent_review(
    pr_diff: PRDiff,
    ollama_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> AgentReview:
    """Run the full agent review loop across all changed files.

    1. For each file, call review_file with accumulated context.
    2. Run cross-file consistency analysis.
    3. Return structured AgentReview.
    """
    review = AgentReview()
    previous_summaries: list[str] = []
    files_summary_parts: list[str] = []

    for file_change in pr_diff.files:
        context = "\n".join(previous_summaries) if previous_summaries else ""

        raw_review = llm_module.review_file(
            diff=file_change.diff,
            filename=file_change.path,
            context=context,
            ollama_url=ollama_url,
            model=model,
        )

        comments = _parse_inline_comments(raw_review, file_change)

        review.comments.extend(comments)
        previous_summaries.append(
            f"File: {file_change.path} ({file_change.status}): {raw_review[:300]}"
        )
        files_summary_parts.append(
            f"- {file_change.path} ({file_change.status}): "
            f"+{file_change.additions} -{file_change.deletions}"
        )

    # Cross-file analysis
    if len(pr_diff.files) > 1:
        files_summary = "\n".join(files_summary_parts)
        cross_raw = llm_module.cross_review(
            files_summary=files_summary,
            ollama_url=ollama_url,
            model=model,
        )
        review.cross_file_comments = _parse_cross_file_comments(
            cross_raw, pr_diff.files
        )
        review.summary = cross_raw[:500]
    else:
        review.summary = f"Reviewed 1 file: {pr_diff.files[0].path}"

    return review


def _parse_inline_comments(
    raw_review: str, file_change: FileChange
) -> list[InlineComment]:
    """Parse structured JSON comment output from the LLM into InlineComment objects.

    Expects JSON like:
    {"comments": [{"line": 10, "severity": "critical", "body": "..."}]}
    """
    import json

    comments: list[InlineComment] = []

    # Try to extract JSON block from the raw review
    json_block = _extract_json(raw_review)
    if json_block is None:
        return comments

    try:
        data = json.loads(json_block)
    except json.JSONDecodeError:
        return comments

    for entry in data.get("comments", []):
        line = entry.get("line", 1)
        position = _map_line_to_position(file_change.diff, line)
        comments.append(
            InlineComment(
                path=file_change.path,
                position=position,
                line=line,
                severity=entry.get("severity", "suggestion"),
                body=entry.get("body", ""),
            )
        )

    return comments


def _parse_cross_file_comments(
    raw_review: str, files: list[FileChange]
) -> list[InlineComment]:
    """Parse cross-file review output into InlineComment objects.

    Expects JSON like:
    {"comments": [{"file": "a.py", "line": 10, "severity": "important", "body": "..."}]}
    """
    import json

    comments: list[InlineComment] = []
    file_map = {f.path: f for f in files}

    json_block = _extract_json(raw_review)
    if json_block is None:
        return comments

    try:
        data = json.loads(json_block)
    except json.JSONDecodeError:
        return comments

    for entry in data.get("comments", []):
        file_path = entry.get("file", "")
        line = entry.get("line", 1)
        severity = entry.get("severity", "suggestion")
        body = entry.get("body", "")

        target_file = file_map.get(file_path)
        if target_file:
            position = _map_line_to_position(target_file.diff, line)
        else:
            # Attach to first file as fallback
            file_path = files[0].path if files else "unknown"
            position = 1

        comments.append(
            InlineComment(
                path=file_path,
                position=position,
                line=line,
                severity=severity,
                body=body,
            )
        )

    return comments


def _extract_json(text: str) -> str | None:
    """Extract a JSON object from text that may contain other content."""
    # Look for ```json ... ``` blocks first
    import re

    code_block = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if code_block:
        return code_block.group(1)

    # Look for raw JSON object
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : i + 1]

    return None
