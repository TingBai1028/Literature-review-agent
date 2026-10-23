"""Command line entry point.

    python -m litagent "your research question" --effort normal --sample-mode
"""

from __future__ import annotations

import argparse
import sys

from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer, CLIReviewer
from litagent.orchestrator import run_pipeline
from litagent.trace import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Literature review agent")
    parser.add_argument("question", help="Your research question")
    parser.add_argument("--effort", choices=[e.value for e in Effort], default="normal")
    parser.add_argument("--sample-mode", action="store_true", help="Run on data/sample/ without Zetaris, Nightshift or network")
    parser.add_argument("--auto-approve", action="store_true", help="Skip human review prompts")
    parser.add_argument("--signed-in", action="store_true", help="Simulate a user signed in with a school account")
    args = parser.parse_args()

    setup_logging()
    settings = Settings()
    if args.sample_mode:
        settings.sample_mode = True
    reviewer = AutoApproveReviewer() if (args.auto_approve or settings.sample_mode) else CLIReviewer()

    try:
        result = run_pipeline(args.question, Effort(args.effort), reviewer, settings, signed_in=args.signed_in)
    except Exception as e:
        print(f"\nError: {type(e).__name__}: {e}  (details in {settings.logs_dir}/)", file=sys.stderr)
        sys.exit(1)

    print(f"\nStatus: {result.status}")
    if result.message_to_user:
        print(result.message_to_user)
    print(f"Papers: {len(result.papers)}  Clusters: {len(result.clusters)}  "
          f"Connections: {len(result.connections)}  Gaps: {len(result.gaps)}")
    for w in result.warnings:
        print(f"Warning: {w}")
    print(f"Trace: {settings.logs_dir}/trace-{result.run_id}.jsonl")


if __name__ == "__main__":
    main()
