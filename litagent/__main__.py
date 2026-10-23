"""Command line entry point.

    python -m litagent "your research question" --effort normal --dry-run
"""

from __future__ import annotations

import argparse

from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer, CLIReviewer
from litagent.orchestrator import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Literature review agent")
    parser.add_argument("question", help="Your research question")
    parser.add_argument("--effort", choices=[e.value for e in Effort], default="normal")
    parser.add_argument("--dry-run", action="store_true", help="Run on fake data without API keys")
    parser.add_argument("--auto-approve", action="store_true", help="Skip human review prompts")
    parser.add_argument("--signed-in", action="store_true", help="Simulate a user signed in with a school account")
    args = parser.parse_args()

    settings = Settings()
    if args.dry_run:
        settings.dry_run = True
    reviewer = AutoApproveReviewer() if (args.auto_approve or args.dry_run) else CLIReviewer()

    result = run_pipeline(args.question, Effort(args.effort), reviewer, settings, signed_in=args.signed_in)

    print(f"\nStatus: {result.status}")
    if result.message_to_user:
        print(result.message_to_user)
    print(f"Papers: {len(result.papers)}  Clusters: {len(result.clusters)}  "
          f"Connections: {len(result.connections)}  Gaps: {len(result.gaps)}")
    for w in result.warnings:
        print(f"Warning: {w}")
    print(f"Trace: {settings.runs_dir}/{result.run_id}.jsonl")


if __name__ == "__main__":
    main()
