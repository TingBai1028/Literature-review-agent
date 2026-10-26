"""Cluster roles: exactly one main cluster, at least one foundation cluster, and side clusters.

Plain code (no LLM). Spec: docs/agents/clusterer.md, "Cluster roles".
- Main: the group most related to the topic (mean question similarity plus the clusterer's LLM relevance
  check), resized to main_cluster_min_size..main_cluster_max_size. A run never ends without one: when no group
  passes, the most relevant papers overall form it and the fallback is logged.
- Foundation: older, highly cited papers the main cluster builds on (cited by main papers), relaxed step by step
  when too few qualify; every relaxation is logged.
- Side: the remaining papers regrouped by content similarity; groups smaller than side_min_size are merged into
  their nearest group so every cluster stays meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

import numpy as np

from litagent.config import Settings
from litagent.schemas import Paper
from litagent.similarity import linkage_groups
from litagent.trace import current_trace

RELEVANCE_BONUS = {"direct": 1.0, "supporting": 0.5}


@dataclass
class RolePlan:
    main: list[int]
    foundation: list[int]
    sides: list[list[int]]
    main_reason: str
    foundation_reason: str
    decisions: list[dict] = field(default_factory=list)


def relevance_scores(question_similarity: np.ndarray, relevance: list[str], settings: Settings) -> np.ndarray:
    """Question cosine plus a bonus from the LLM relevance check (direct 1, supporting 0.5)."""
    return np.asarray(question_similarity, dtype=float) + settings.main_relevance_weight * np.array(
        [RELEVANCE_BONUS.get(r, 0.0) for r in relevance])


def assign_roles(papers: list[Paper], similarity: np.ndarray, question_similarity: np.ndarray,
                 relevance: list[str], settings: Settings) -> RolePlan:
    validate_role_settings(settings)
    n = len(papers)
    scores = relevance_scores(question_similarity, relevance, settings)
    ranked = sorted(range(n), key=lambda i: (-scores[i], papers[i].id))
    plan = RolePlan([], [], [], "", "")
    plan.main, plan.main_reason = _main(papers, similarity, question_similarity, relevance, scores, ranked, settings, plan)
    rest = [i for i in ranked if i not in set(plan.main)]
    plan.foundation, plan.foundation_reason = _foundation(papers, plan.main, rest, question_similarity, relevance, settings)
    remaining = sorted((i for i in rest if i not in set(plan.foundation)), key=lambda i: papers[i].id)
    plan.sides = side_groups(papers, similarity, remaining, settings, plan.decisions)
    if trace := current_trace():
        trace.log("clusterer", "assign cluster roles", f"main {len(plan.main)}, foundation {len(plan.foundation)}, "
                  f"{len(plan.sides)} side", result={"main": [papers[i].id for i in plan.main],
                  "foundation": [papers[i].id for i in plan.foundation], "decisions": plan.decisions},
                  why=f"{plan.main_reason} {plan.foundation_reason}", step_kind="code")
    return plan


def validate_role_settings(settings: Settings) -> None:
    if not (1 <= settings.main_cluster_min_size <= settings.main_cluster_max_size
            and 1 <= settings.foundation_min_size <= settings.foundation_max_size and settings.side_min_size >= 1
            and 0 <= settings.main_relevance_weight <= 1):
        raise ValueError("Cluster role sizes must be positive with min <= max, and main_relevance_weight in [0, 1]")


def _main(papers, similarity, question_similarity, relevance, scores, ranked, settings, plan) -> tuple[list[int], str]:
    low, high = settings.main_cluster_min_size, settings.main_cluster_max_size
    groups = [g for g in linkage_groups(similarity, settings.side_similarity_threshold, settings.side_linkage) if len(g) > 1]
    def summary(group):
        return float(np.mean(question_similarity[group])), sum(relevance[i] == "direct" for i in group)
    passing = [g for g in groups if summary(g)[0] >= settings.main_similarity_threshold or summary(g)[1]]
    if passing:
        best = max(passing, key=lambda g: (float(np.mean(scores[g])), -min(ranked.index(i) for i in g)))
        mean, direct = summary(best)
        members = sorted(best, key=ranked.index)[:high]
        trimmed = len(best) - len(members)
        reason = (f"Chosen as main: of {len(groups)} candidate groups it is the most related to the topic "
                  f"(mean question similarity {mean:.2f}; {direct} of {len(best)} papers judged directly relevant).")
        if trimmed:
            reason += f" Kept its {high} most relevant papers; {trimmed} moved to other clusters."
            plan.decisions.append({"step": "main size", "decision": f"trimmed {trimmed}", "why": f"main is capped at {high}"})
    else:
        count = sum(question_similarity[i] >= settings.main_similarity_threshold for i in ranked)
        members = ranked[:min(max(count, low), high)]
        reason = (f"Fallback main: no group of 2+ papers reached question similarity {settings.main_similarity_threshold} "
                  f"or had a paper judged directly relevant, so the {len(members)} most relevant papers overall form it.")
        plan.decisions.append({"step": "main fallback", "decision": "top papers overall", "why": reason})
    # Papers judged directly relevant join main up to its maximum (real run 26 Oct: the best group held only 4
    # of the many direct LLM-evaluation papers; grouping had split the rest off).
    direct = [i for i in ranked if i not in members and relevance[i] == "direct"][:max(0, high - len(members))]
    if direct:
        members += direct
        reason += f" Added {len(direct)} more papers judged directly relevant (main holds up to {high})."
        plan.decisions.append({"step": "main size", "decision": f"added {len(direct)} direct",
                               "why": "papers judged directly relevant belong in main even when grouping split them off"})
    added = [i for i in ranked if i not in members][:max(0, low - len(members))]
    if added:
        members += added
        reason += f" Added the {len(added)} next most relevant papers to reach {low}."
        plan.decisions.append({"step": "main size", "decision": f"added {len(added)}", "why": f"main needs at least {low}"})
    return sorted(members, key=ranked.index), reason


def _foundation(papers, main, rest, question_similarity, relevance, settings) -> tuple[list[int], str]:
    if not rest:
        return [], "No papers left for a foundation cluster."
    years = [p.year for p in papers if p.year]
    cites = [p.citation_count or 0 for p in papers]
    median_year = median(years) if years else None
    median_cites = median(cites) if cites else 0
    cited_by_main = {ref for i in main for ref in (papers[i].references or [])}
    old = lambda i: median_year is not None and papers[i].year is not None and papers[i].year < median_year
    highly_cited = lambda i: (papers[i].citation_count or 0) > 0 and (papers[i].citation_count or 0) >= median_cites
    by_citations = lambda ids: sorted(ids, key=lambda i: (-(papers[i].citation_count or 0), papers[i].year or 9999, papers[i].id))
    # A citation from main papers ties a paper to the topic; the relaxed rules must establish it another way
    # (real run 26 Oct: a protein-language review was chosen as foundation for an LLM question).
    # The LLM relevance check decides; the question-similarity gate cannot, because retrieval already drops every
    # paper below it (the protein review scored 0.54 but was judged "uncertain": not about human languages).
    # Only when no paper was checked (sample mode) does the gate stand in.
    checked = any(r != "uncertain" for r in relevance)
    on_topic = lambda i: (relevance[i] in ("direct", "supporting") if checked
                          else question_similarity[i] >= settings.main_similarity_threshold)
    tiers = [("cited by main papers, older than the median year and at least median citations",
              [i for i in rest if papers[i].id in cited_by_main and old(i) and highly_cited(i)]),
             ("on topic, older than the median year and at least median citations (not required to be cited by main)",
              [i for i in rest if on_topic(i) and old(i) and highly_cited(i)]),
             ("the most cited on-topic remaining papers", [i for i in rest if on_topic(i)]),
             ("the most cited remaining papers (no on-topic paper left)", list(rest))]
    chosen, used, relaxed = [], [], False
    last = len(tiers) - 1
    for tier, (description, candidates) in enumerate(tiers):
        new = [i for i in by_citations(candidates) if i not in chosen]
        if tier == last and chosen:
            break  # the off-topic last resort only guarantees that a foundation cluster exists
        if new and len(chosen) < settings.foundation_min_size:
            # The strict rule fills up to the maximum, relaxed on-topic rules up to the minimum, and the off-topic
            # last resort adds a single paper.
            limit = (settings.foundation_max_size if tier == 0 else
                     1 if tier == last else settings.foundation_min_size)
            chosen += new[:limit - len(chosen)]
            used.append(f"{len(new)} {description}")
            relaxed |= tier > 0
    year = f"{median_year:g}" if median_year is not None else "unknown"
    reason = (f"Foundation: {len(chosen)} classic papers (median year of the set {year}, "
              f"median citations {median_cites:g}); candidates: " + "; then ".join(used) + ".")
    if relaxed:
        reason += " Fewer than " + str(settings.foundation_min_size) + " papers met the strict rule, so it was relaxed."
    return chosen, reason


def side_groups(papers: list[Paper], similarity: np.ndarray, remaining: list[int], settings: Settings,
                decisions: list[dict]) -> list[list[int]]:
    """Group the papers at `remaining` by linkage; groups under side_min_size merge into their nearest group."""
    if not remaining:
        return []
    block = similarity[np.ix_(remaining, remaining)]
    groups = [[remaining[i] for i in g] for g in linkage_groups(block, settings.side_similarity_threshold, settings.side_linkage)]
    large = [g for g in groups if len(g) >= settings.side_min_size]
    small = [g for g in groups if len(g) < settings.side_min_size]
    if not large:
        if len(groups) > 1:
            decisions.append({"step": "side groups", "decision": "merged all into one",
                                   "why": f"no group reached {settings.side_min_size} papers"})
        return [sorted(remaining, key=lambda i: papers[i].id)]
    for group in small:
        target = max(large, key=lambda g: (float(similarity[np.ix_(group, g)].mean()), -g[0]))
        target += group
        decisions.append({"step": "side groups", "decision": f"merged {len(group)} paper(s)",
                               "why": f"groups under {settings.side_min_size} papers join their most similar side group",
                               "paper_ids": [papers[i].id for i in group]})
    return [sorted(g, key=lambda i: papers[i].id) for g in large]
