"""LLM client for PR code review."""

import json
import urllib.request
import urllib.error
import os


SYSTEM_PROMPT = """You are an expert code reviewer. Analyze the PR diff and provide constructive feedback.

Rules:
- Focus on: bugs, security issues, performance, code quality, best practices
- Be specific: reference file names and line numbers when possible
- Be constructive: suggest improvements, not just problems
- Use markdown formatting
- Group issues by severity: Critical, Important, Suggestion
- If the code looks good, say so! Don't invent problems.
- Be concise — developers don't want to read essays

Output format:
## Review Summary
[Brief overall assessment]

## Critical Issues
[Issues that must be fixed]

## Important Issues
[Issues that should be fixed]

## Suggestions
[Nice-to-have improvements]"""


def review_diff(
    diff_prompt: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> str:
    """Generate code review for a PR diff."""
    user_prompt = f"""Review this PR diff:

{diff_prompt}"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }

    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["message"]["content"].strip()
    except urllib.error.URLError:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return _review_openai(diff_prompt, openai_key)
        raise ConnectionError(
            f"Cannot connect to Ollama at {ollama_url}. "
            "Start Ollama: ollama serve"
        )


def _review_openai(diff_prompt: str, api_key: str) -> str:
    """Fallback to OpenAI."""
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this PR diff:\n\n{diff_prompt}"},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()


FILE_REVIEW_PROMPT = """You are an expert code reviewer. Analyze this file's diff and produce inline review comments.

Rules:
- Focus on: bugs, security issues, performance, code quality, best practices
- Be specific: reference exact line numbers in the NEW file
- Be constructive: suggest improvements, not just problems
- Be concise -- one sentence per comment when possible
- If the code looks good, return an empty comments array

You MUST respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{
  "comments": [
    {"line": <line_number>, "severity": "<critical|important|suggestion>", "body": "<comment text>"}
  ]
}

If there are no issues, return: {"comments": []}"""


CROSS_REVIEW_PROMPT = """You are an expert code reviewer performing a cross-file consistency analysis.

Given a summary of all changed files in a PR, identify issues that span multiple files:
- Interface/implementation mismatches (updated one but not the other)
- Missing test coverage for changed code
- Inconsistent naming or patterns across files
- Type signature changes not propagated to callers
- API changes without corresponding client updates

You MUST respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{
  "comments": [
    {"file": "<filename>", "line": 1, "severity": "<critical|important|suggestion>", "body": "<comment text>"}
  ],
  "summary": "<brief overall assessment>"
}

If there are no cross-file issues, return: {"comments": [], "summary": "No cross-file issues found."}"""


def review_file(
    diff: str,
    filename: str,
    context: str = "",
    ollama_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> str:
    """Generate inline review comments for a single file diff.

    Args:
        diff: The unified diff text for the file.
        filename: The file path/name.
        context: Accumulated context from reviewing previous files.
        ollama_url: Ollama API URL.
        model: Model name to use.

    Returns:
        Raw LLM response (expected to be JSON).
    """
    user_parts = [f"Review this file diff: {filename}", "", diff]
    if context:
        user_parts.append("")
        user_parts.append(f"Context from other files reviewed so far:\n{context}")

    user_prompt = "\n".join(user_parts)
    return _call_llm(FILE_REVIEW_PROMPT, user_prompt, ollama_url, model)


def cross_review(
    files_summary: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> str:
    """Perform cross-file consistency review.

    Args:
        files_summary: Summary of all changed files with their descriptions.
        ollama_url: Ollama API URL.
        model: Model name to use.

    Returns:
        Raw LLM response (expected to be JSON).
    """
    user_prompt = f"Analyze these changed files for cross-file issues:\n\n{files_summary}"
    return _call_llm(CROSS_REVIEW_PROMPT, user_prompt, ollama_url, model)


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> str:
    """Call LLM with given system and user prompts."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }

    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["message"]["content"].strip()
    except urllib.error.URLError:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return _call_llm_openai(system_prompt, user_prompt, openai_key)
        raise ConnectionError(
            f"Cannot connect to Ollama at {ollama_url}. "
            "Start Ollama: ollama serve"
        )


def _call_llm_openai(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """Call OpenAI as fallback."""
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()


def check_ollama(ollama_url: str = "http://localhost:11434") -> bool:
    """Check if Ollama is running."""
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False
