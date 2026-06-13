# AI PR Reviewer Bot 🤖📝

A GitHub Action that automatically reviews pull requests using AI and posts review comments. Uses Ollama for local LLM inference (with OpenAI fallback).

## What It Does

1. **Triggers** on PR open/sync events
2. **Parses** the PR diff into structured data
3. **Reviews** code changes using AI (Ollama)
4. **Posts** review comments on the PR

## Quick Start

### Review a PR locally
```bash
# Review PR #123
python src/main.py 123

# Review and post comment
python src/main.py 123 --comment

# Review unstaged changes
python src/main.py --unstaged

# Output as JSON
python src/main.py 123 --output json
```

### GitHub Action
Add to `.github/workflows/review.yml`:
```yaml
name: AI PR Review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: AkiraKane/ai-pr-reviewer@v1
        with:
          pr_number: ${{ github.event.pull_request.number }}
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PR Event      │────▶│  Diff Parser    │────▶│   LLM Client    │
│   (GitHub)      │     │  (structured)   │     │   (Ollama)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │                         │
                              ▼                         ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │   PRDiff        │────▶│   Review        │
                        │   .to_prompt()  │     │   (markdown)    │
                        └─────────────────┘     └─────────────────┘
```

## Features

- **Smart Parsing**: Extracts file changes, additions/deletions, diff content
- **AI Review**: Analyzes code for bugs, security issues, performance, best practices
- **GitHub Integration**: Posts comments directly on PRs via `gh` CLI
- **Multiple Modes**: Review PRs, unstaged changes, or staged changes
- **Severity Grouping**: Categorizes issues as Critical, Important, or Suggestion

## Review Categories

The AI reviewer looks for:
- 🐛 **Bugs**: Logic errors, edge cases, null pointer issues
- 🔒 **Security**: SQL injection, XSS, hardcoded secrets, insecure patterns
- ⚡ **Performance**: Inefficient algorithms, N+1 queries, memory leaks
- 📋 **Best Practices**: Code style, naming, documentation, error handling
- 🏗️ **Architecture**: SOLID principles, separation of concerns, coupling

## Requirements

- Python 3.11+
- `gh` CLI (authenticated)
- Ollama running locally (or OPENAI_API_KEY)

## Installation

```bash
git clone https://github.com/AkiraKane/ai-pr-reviewer.git
cd ai-pr-reviewer
pip install -r requirements.txt  # No dependencies! (stdlib only)
```

## Docker

```bash
docker build -t ai-pr-reviewer .
docker run -v ~/.config/gh:/root/.config/gh:ro ai-pr-reviewer python main.py 123
```

## Interview Talking Points

- **CI/CD Automation**: Integrates AI into the PR review workflow
- **GitHub API**: Uses `gh` CLI for secure, authenticated access
- **Prompt Engineering**: Structured prompts that produce actionable feedback
- **Developer Experience**: Automates tedious code review tasks

## License

MIT
