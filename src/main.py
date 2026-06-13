#!/usr/bin/env python3
"""AI PR Reviewer — review PRs using AI and post comments to GitHub."""

import argparse
import json
import subprocess
import sys
import os

from diff_parser import get_pr_diff, get_unstaged_diff, get_staged_diff, PRDiff
from llm import review_diff, check_ollama


def main():
    parser = argparse.ArgumentParser(
        description="AI-powered PR code review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 123                        # Review PR #123
  %(prog)s 123 --comment              # Review and post comment
  %(prog)s 123 --agent                # Multi-file agent review
  %(prog)s 123 --agent --inline       # Agent review with inline comments
  %(prog)s 123 --agent --inline --watch  # CI mode: exit 1 on critical issues
  %(prog)s --unstaged                 # Review unstaged changes
  %(prog)s --staged                   # Review staged changes
  %(prog)s --pr 123 --output json    # Output review as JSON
        """,
    )
    parser.add_argument("pr", nargs="?", type=int,
                        help="PR number to review")
    parser.add_argument("--unstaged", action="store_true",
                        help="Review unstaged changes")
    parser.add_argument("--staged", action="store_true",
                        help="Review staged changes")
    parser.add_argument("--comment", action="store_true",
                        help="Post review as PR comment")
    parser.add_argument("--agent", action="store_true",
                        help="Multi-file agent review with cross-referencing")
    parser.add_argument("--inline", action="store_true",
                        help="Post inline review comments (requires --agent)")
    parser.add_argument("--watch", action="store_true",
                        help="Exit with non-zero code if critical issues found (for CI)")
    parser.add_argument("--output", choices=["markdown", "json"],
                        default="markdown", help="Output format")
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama API URL")
    parser.add_argument("--model", default="llama3.2",
                        help="Ollama model to use")
    parser.add_argument("--repo", default=".",
                        help="Path to git repository")

    args = parser.parse_args()

    # Validate arguments
    if not args.pr and not args.unstaged and not args.staged:
        parser.error("Must specify PR number, --unstaged, or --staged")

    if args.inline and not args.agent:
        parser.error("--inline requires --agent mode")

    if args.watch and not args.agent:
        parser.error("--watch requires --agent mode")

    # Check Ollama
    if not check_ollama(args.ollama_url):
        if not os.environ.get("OPENAI_API_KEY"):
            print("Error: Neither Ollama nor OPENAI_API_KEY available.",
                  file=sys.stderr)
            sys.exit(1)

    # Agent mode (PR only)
    if args.agent:
        if not args.pr:
            parser.error("--agent mode requires a PR number")
        _run_agent_mode(args)
        return

    # Standard mode
    _run_standard_mode(args)


def _run_standard_mode(args):
    """Run the standard (non-agent) review flow."""
    # Get diff
    if args.unstaged:
        diff = get_unstaged_diff(args.repo)
        if not diff:
            print("No unstaged changes found.", file=sys.stderr)
            sys.exit(0)
        prompt = f"Review these unstaged changes:\n\n{diff}"
    elif args.staged:
        diff = get_staged_diff(args.repo)
        if not diff:
            print("No staged changes found.", file=sys.stderr)
            sys.exit(0)
        prompt = f"Review these staged changes:\n\n{diff}"
    else:
        pr_diff = get_pr_diff(args.pr, args.repo)
        if not pr_diff.files:
            print(f"No changes found in PR #{args.pr}", file=sys.stderr)
            sys.exit(0)
        prompt = pr_diff.to_prompt()
        print(f"PR #{pr_diff.pr_number}: {pr_diff.title}")
        print(f"Files: {pr_diff.file_count}, +{pr_diff.total_additions} -{pr_diff.total_deletions}")
        print()

    # Generate review
    print("Generating review...")
    try:
        review = review_diff(prompt, ollama_url=args.ollama_url, model=args.model)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    if args.output == "json":
        output = {
            "pr_number": args.pr,
            "review": review,
        }
        print(json.dumps(output, indent=2))
    else:
        print(review)

    # Post comment if requested
    if args.comment and args.pr:
        _post_comment(args.pr, review, args.repo)


def _run_agent_mode(args):
    """Run the multi-file agent review flow."""
    from agent import run_agent_review

    pr_diff = get_pr_diff(args.pr, args.repo)
    if not pr_diff.files:
        print(f"No changes found in PR #{args.pr}", file=sys.stderr)
        sys.exit(0)

    print(f"PR #{pr_diff.pr_number}: {pr_diff.title}")
    print(f"Files: {pr_diff.file_count}, +{pr_diff.total_additions} -{pr_diff.total_deletions}")
    print()

    # Run agent review
    print("Running agent review...")
    try:
        agent_review = run_agent_review(
            pr_diff,
            ollama_url=args.ollama_url,
            model=args.model,
        )
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    if args.output == "json":
        output = {
            "pr_number": args.pr,
            **agent_review.to_json_dict(),
        }
        print(json.dumps(output, indent=2))
    else:
        print(agent_review.to_markdown())

    # Post inline comments if requested
    if args.inline and args.pr:
        from github_api import post_inline_review
        result = post_inline_review(
            pr_number=args.pr,
            comments=agent_review.all_comments,
            body=agent_review.summary,
            repo_path=args.repo,
        )
        if result.success:
            print(f"\nInline review posted on PR #{args.pr}")
            if result.review_url:
                print(f"  {result.review_url}")
        else:
            print(f"\nFailed to post inline review: {result.error}", file=sys.stderr)
            sys.exit(1)
    elif args.comment and args.pr:
        # Fall back to single comment
        _post_comment(args.pr, agent_review.to_markdown(), args.repo)

    # Watch mode: exit non-zero on critical issues
    if args.watch and agent_review.has_critical:
        print(
            f"\nCI check failed: {agent_review.critical_count} critical issue(s) found.",
            file=sys.stderr,
        )
        sys.exit(1)


def _post_comment(pr_number: int, review: str, repo_path: str):
    """Post review as PR comment."""
    comment = f"""## AI Code Review

{review}

---
*Generated by [AI PR Reviewer](https://github.com/AkiraKane/ai-pr-reviewer)*
"""
    result = subprocess.run(
        ["gh", "pr", "comment", str(pr_number), "--body", comment],
        capture_output=True, text=True, cwd=repo_path
    )
    if result.returncode == 0:
        print(f"\nComment posted on PR #{pr_number}")
    else:
        print(f"\nFailed to post comment: {result.stderr}", file=sys.stderr)


if __name__ == "__main__":
    main()
