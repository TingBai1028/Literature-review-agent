"""Integration probe: a deliberately answered question must be caught by coverage.

This tests the real OpenAlex/coverage component. It does NOT propose or save a research gap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.agents.gap_finder import _Run  # noqa: E402
from litagent.cluster_state import effective_settings, load_version  # noqa: E402
from litagent.config import EFFORT_PROFILES, Settings  # noqa: E402
from litagent.finding_engine import FindingContext  # noqa: E402
from litagent.integrations.llm import TokenMeter  # noqa: E402
from litagent.schemas import Gap  # noqa: E402
from litagent.trace import Trace, mask, setup_logging  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("logs/coverage-integration-probe.json"))
    args = parser.parse_args()
    setup_logging()
    source, state, arrays = load_version(args.run_id, Settings(sample_mode=False))
    cfg = effective_settings(state, Settings(sample_mode=False))
    a, b = state.papers[0].id, state.papers[1].id  # any two map papers; coverage excludes them from the results
    probe = Gap(id="known-covered-probe", cluster_id="probe", between_paper_ids=[a, b], evidence=[],
        description="Paper A shows LoRA adapts LLMs cheaply. Paper B shows LLMs translate low-resource languages poorly. "
                    "No work combines them to fine-tune LLMs with language-specific LoRA for low-resource machine translation.",
        why_it_matters="Deliberately answered test question: verify that an evidenced existing study is detected.",
        coverage_query="LoRA low resource machine translation")
    with Trace(cfg.logs_dir) as trace, TokenMeter(EFFORT_PROFILES[state.effort].token_budget) as meter:
        context = FindingContext(question=source.question, similarity=arrays.similarity,
            use_full_text=source.use_full_text, deadline=time.monotonic() + cfg.run_timeout_s)
        run = _Run(state.papers, {}, None, cfg, context)
        kept = run.coverage([probe])
        outcome = run.outcomes.get(probe.id, {})
        report = {"kind": "known_answer_coverage_component_probe", "run_id": trace.run_id,
            "source_run_id": source.run_id, "creates_research_gap": False,
            "expected": "filled", "passed": not kept and outcome.get("stage") == "coverage",
            "outcome": outcome, "coverage": kept[0].coverage.model_dump(mode="json") if kept else None,
            "usage": meter.usage.model_dump()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"Coverage probe: {'filled' if report['passed'] else kept[0].coverage_status}; {outcome.get('reason')}; report: {args.output}")
        return 0 if report["passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(mask(f"FAILED: {type(error).__name__}: {error}"), file=sys.stderr)
        raise SystemExit(1)
