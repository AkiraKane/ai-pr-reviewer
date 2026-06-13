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


def check_ollama(ollama_url: str = "http://localhost:11434") -> bool:
    """Check if Ollama is running."""
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False
