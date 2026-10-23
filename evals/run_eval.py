"""Run the agent on every topic in evals/topics.yaml and save results.

    python -m evals.run_eval              # real run
    python -m evals.run_eval --dry-run    # check the harness works
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer
from litagent.orchestrator import run_pipeline

TOPICS = Path(__file__).parent / "topics.yaml"
OUT = Path(__file__).parent / "results.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    settings.dry_run = args.dry_run
    topics = yaml.safe_load(TOPICS.read_text(encoding="utf-8"))["topics"]

    results = []
    for t in topics:
        result = run_pipeline(t["question"], Effort(t.get("effort", "normal")), AutoApproveReviewer(), settings)
        results.append(
            {
                "id": t["id"],
                "status": result.status,
                "clusters": [c.label for c in result.clusters],
                "gaps": [g.description for g in result.gaps],
                "warnings": result.warnings,
                "expected_clusters": t.get("expected_clusters", []),
                "expected_gaps": t.get("expected_gaps", []),
                # TODO: compute cluster agreement and gap recall here (an LLM judge can match labels to expected ones)
            }
        )
        print(f"{t['id']}: {result.status}, {len(result.clusters)} clusters, {len(result.gaps)} gaps")

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
