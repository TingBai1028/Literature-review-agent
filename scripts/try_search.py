"""Try the Planner, Retriever and summary on a real question (Nightshift + OpenAlex, no Zetaris).

    python scripts/try_search.py "How do LLMs handle low-resource languages?"
    python scripts/try_search.py "graph neural networks for drug discovery" --effort medium
    python scripts/try_search.py "graph neural networks for drug discovery" --feedback "only review papers"

Prints the plan, the top papers and the Human review 1 summary, plus time and tokens used.
With --feedback, it re-plans once with that feedback (like Human review 1 rejecting) and searches again.
Use it to tune prompts/planner.md and prompts/retrieval_summary.md. A trace is written to logs/.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.agents import planner, retriever  # noqa: E402
from litagent.config import Effort, Settings  # noqa: E402
from litagent.integrations.llm import TokenMeter  # noqa: E402
from litagent.schemas import SearchPlan  # noqa: E402
from litagent.trace import Trace, mask  # noqa: E402


def show_plan(plan: SearchPlan) -> None:
    c = plan.criteria
    print(f"  topic:      {c.topic}")
    print(f"  years:      {c.year_from or '...'}–{c.year_to or 'now'}")
    print(f"  types:      {', '.join(c.paper_types)}")
    if c.min_citations or c.min_citations_per_year:
        print(f"  citations:  min {c.min_citations or '-'} total, {c.min_citations_per_year or '-'} per year")
    print(f"  queries:    {plan.queries}")
    print(f"  defaults:   {plan.used_defaults or 'none'}")
    print(f"  rationale:  {plan.rationale}")
    print(f"  limit:      {plan.max_papers} papers, {plan.token_budget:,} tokens")


def search(plan: SearchPlan, settings: Settings, top: int) -> None:
    papers = retriever.retrieve(plan, settings)
    if not papers:
        print(f"\nNo papers: {retriever.no_results_message(plan)}")
        return
    print(f"\n== Retriever: {len(papers)} papers (top {min(top, len(papers))}) ==")
    for i, p in enumerate(papers[:top], 1):
        kind = "review" if p.is_review else "study"
        print(f"  {i:>2}. {p.year} {p.citation_count or 0:>5} cites  {kind:<6} {p.title[:90]}")
    print("\n== Summary for Human review 1 ==")
    print("  " + retriever.summarise(papers, plan, settings).summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--effort", choices=[e.value for e in Effort], default="normal")
    parser.add_argument("--feedback", help="Re-plan once with this feedback, then search again")
    parser.add_argument("--top", type=int, default=10, help="How many papers to print")
    parser.add_argument("--plan-only", action="store_true", help="Skip the search (saves OpenAlex calls while tuning the Planner)")
    args = parser.parse_args()

    settings = Settings()
    settings.sample_mode = False
    effort = Effort(args.effort)
    start = time.monotonic()
    try:
        with Trace(settings.logs_dir) as trace, TokenMeter() as meter:
            result = planner.plan(args.question, effort, settings)
            print(f"\n== Planner ({settings.llm_model}) ==")
            if result.status == "need_topic":
                print(f"  no clear topic -> {result.message_to_user}")
            else:
                show_plan(result.plan)
                if not args.plan_only:
                    search(result.plan, settings, args.top)
                if args.feedback:
                    replanned = planner.plan(args.question, effort, settings, args.feedback, result.plan)
                    print(f"\n== Re-plan with feedback: {args.feedback!r} ==")
                    if replanned.status == "need_topic":
                        print(f"  no clear topic -> {replanned.message_to_user}")
                    else:
                        show_plan(replanned.plan)
                        if not args.plan_only:
                            search(replanned.plan, settings, args.top)
    except Exception as e:
        print(f"\nFAILED: {type(e).__name__}: {mask(str(e))[:500]}", file=sys.stderr)
        return 1

    u = meter.usage
    print(f"\n{time.monotonic() - start:.1f} s, {u.prompt_tokens:,} prompt + {u.completion_tokens:,} completion tokens "
          f"in {u.llm_calls} LLM calls. Trace: {trace.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
