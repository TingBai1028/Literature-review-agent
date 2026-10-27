"""Size real saved finding-grade payloads offline; no model, search, or snapshot writes.

Example: python scripts/check_grading_payloads.py --run-id SAVED_RUN --output /tmp/grading-payloads.json
The simulated grades are transport fixtures, not semantic evaluation results.
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.agents import grader
from litagent.cluster_state import file_hash, load_version, path_for
from litagent.config import Settings
from litagent.schemas import Grade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--logs-dir", default="logs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings(sample_mode=False, logs_dir=args.logs_dir)
    result, state, _ = load_version(args.run_id, settings)
    snapshot_paths = [path_for(settings, prefix, args.run_id) for prefix in ("cluster-map", "cluster-state")]
    before = [file_hash(path) for path in snapshot_paths]
    stages = {}
    original_batches = grader._finding_batches
    for stage in ("connections", "gaps"):
        calls, unbatched = [], []

        def plan(payload, cfg):
            unbatched.append(len(json.dumps(payload, ensure_ascii=False)))
            return original_batches(payload, cfg)

        def capture(prompt, message, schema, **kwargs):
            calls.append((len(message), json.loads(message)))
            return Grade(stage=stage, accuracy=3, appropriateness=3, actionability=2,
                         reasoning="Offline transport fixture; no semantic judgment was made.")

        context = SimpleNamespace(question=result.question, audits=result.analysis.audits if result.analysis else [])
        scope = grader.finding_scope(context, stage)
        with patch.object(grader, "_finding_batches", plan), patch.object(grader, "complete_json", capture):
            grader.grade(stage, getattr(result, stage), state.papers, settings, **scope, retry_timeout=False)
        if not calls:
            raise ValueError(f"{stage} failed deterministic source checks before grading")
        accepted = [item["id"] for _, payload in calls for item in payload["output"]]
        pairs = [pair["pair_id"] for _, payload in calls for pair in payload["reviewed_pairs"] or []]
        stages[stage] = {
            "findings": len(accepted), "reviewed_pairs": len(pairs), "batches": len(calls),
            "unbatched_input_chars": unbatched[0], "batch_input_chars": [size for size, _ in calls],
            "max_input_chars": max(size for size, _ in calls),
            "all_findings_once": accepted == [item.id for item in getattr(result, stage)],
            "all_reviewed_pairs_once": sorted(pairs) == sorted(pair["pair_id"] for pair in scope.get("reviewed_pairs", [])),
        }
    receipt = {"scope": "Offline payload sizing on a real saved map; model responses are fixtures, not accuracy or latency results.",
               "run_id": args.run_id, "paper_count": len(state.papers), "input_char_cap": settings.finding_grader_max_input_chars,
               "batch_size": settings.finding_grader_batch_size, "stages": stages,
               "source_snapshots_unchanged": before == [file_hash(path) for path in snapshot_paths]}
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
