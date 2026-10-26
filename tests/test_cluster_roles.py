"""Cluster roles (litagent/cluster_roles.py): one main of 5-10, foundation work, side clusters of 3+; plain code."""

import numpy as np

from litagent.cluster_roles import assign_roles
from litagent.config import Settings
from litagent.schemas import Paper
from litagent.trace import Trace


def papers(n, **overrides):
    out = [Paper(id=f"P{i:02d}", title=f"Paper {i}", source="openalex", year=2024, citation_count=1) for i in range(n)]
    for pid, fields in overrides.items():
        for key, value in fields.items():
            setattr(out[int(pid[1:])], key, value)
    return out


def blocks(*sizes, within=.9, across=.2):
    """Similarity matrix of groups of the given sizes, in order."""
    labels = np.repeat(np.arange(len(sizes)), sizes)
    m = np.where(labels[:, None] == labels[None, :], within, across)
    np.fill_diagonal(m, 1)
    return m


def test_main_is_the_most_relevant_group_trimmed_to_ten():
    ps = papers(20)
    question = np.r_[np.linspace(.9, .8, 12), np.full(8, .3)]
    plan = assign_roles(ps, blocks(12, 8), question, ["uncertain"] * 20, Settings())
    assert plan.main == list(range(10)) and "Kept its 10 most relevant papers; 2 moved" in plan.main_reason
    assert not set(plan.main) & set(plan.foundation) and not set(plan.main) & {i for g in plan.sides for i in g}


def test_small_main_is_filled_with_the_next_most_relevant_papers():
    ps = papers(12)
    question = np.array([.9, .85, .6, .55, .5, .45, .3, .3, .2, .2, .1, .1])
    plan = assign_roles(ps, blocks(2, 10), question, ["uncertain"] * 12, Settings())
    assert plan.main == [0, 1, 2, 3, 4] and "Added the 3 next most relevant papers to reach 5" in plan.main_reason


def test_main_is_filled_with_supporting_papers_before_unjudged_ones():
    ps = papers(12)
    question = np.array([.9, .85, .6, .55, .5, .45, .3, .3, .2, .2, .1, .1])
    relevance = ["uncertain"] * 6 + ["supporting"] * 3 + ["uncertain"] * 3
    plan = assign_roles(ps, blocks(2, 10), question, relevance, Settings())
    # Real run 27 Oct: an off-topic paper filled main on cosine alone while on-topic supporting papers stayed out.
    assert sorted(plan.main) == [0, 1, 6, 7, 8] and "supporting before unjudged" in plan.main_reason


def test_llm_relevance_check_can_outweigh_a_slightly_higher_cosine():
    ps = papers(10)
    question = np.r_[np.full(5, .62), np.full(5, .6)]
    relevance = ["uncertain"] * 5 + ["direct"] * 5
    plan = assign_roles(ps, blocks(5, 5), question, relevance, Settings())
    assert plan.main == [5, 6, 7, 8, 9] and "5 of 5 papers judged directly relevant" in plan.main_reason


def test_no_passing_group_falls_back_to_the_top_papers_and_logs_it(tmp_path):
    ps = papers(12)
    question = np.linspace(.4, .1, 12)
    with Trace(str(tmp_path)) as trace:
        plan = assign_roles(ps, blocks(4, 4, 4), question, ["supporting"] * 12, Settings())
    assert plan.main == [0, 1, 2, 3, 4] and plan.main_reason.startswith("Fallback main")
    event = next(e for e in trace.events if e["action"] == "assign cluster roles")
    assert event["step_kind"] == "code" and "main fallback" in str(event["result"])


def test_foundation_prefers_old_highly_cited_papers_cited_by_main():
    old = {"year": 2005, "citation_count": 900}
    ps = papers(14, P00={"references": ["P10", "P11", "P12"]}, P01={"references": ["P13"]},
                P10=old, P11=old, P12=old, P13={"year": 2006, "citation_count": 50}, P05=old)
    question = np.r_[np.full(5, .9), np.full(9, .2)]
    plan = assign_roles(ps, blocks(5, 9), question, ["uncertain"] * 14, Settings())
    assert [ps[i].id for i in plan.foundation] == ["P10", "P11", "P12", "P13"]
    assert "cited by main papers" in plan.foundation_reason and "relaxed" not in plan.foundation_reason


def test_foundation_relaxes_step_by_step_and_says_so():
    ps = papers(10, P07={"year": 2001, "citation_count": 500})
    question = np.r_[np.full(5, .9), np.full(5, .2)]
    relevance = ["uncertain"] * 5 + ["supporting"] * 5  # the rest is on topic, just less related
    plan = assign_roles(ps, blocks(5, 5), question, relevance, Settings())
    assert len(plan.foundation) == 3 and ps[plan.foundation[0]].id == "P07"
    assert "relaxed" in plan.foundation_reason and "most cited on-topic" in plan.foundation_reason


def test_off_topic_classics_are_not_foundation_while_on_topic_papers_remain():
    # Real run, 26 Oct: a highly cited protein-language review became foundation for an LLM question.
    ps = papers(12, P05={"year": 2001, "citation_count": 900}, P06={"year": 2015, "citation_count": 40})
    question = np.r_[np.full(5, .9), .1, np.full(6, .6)]  # P05 is off topic
    plan = assign_roles(ps, blocks(5, 7), question, ["uncertain"] * 12, Settings())
    assert "P05" not in [ps[i].id for i in plan.foundation] and ps[plan.foundation[0]].id == "P06"
    offtopic = assign_roles(ps, blocks(5, 7), np.r_[np.full(5, .9), np.full(7, .1)], ["uncertain"] * 12, Settings())
    assert len(offtopic.foundation) == 1 and "no on-topic paper left" in offtopic.foundation_reason


def test_papers_judged_directly_relevant_join_main_up_to_ten():
    ps = papers(16)
    question = np.r_[np.full(4, .8), np.full(12, .55)]
    relevance = ["direct"] * 4 + ["direct"] * 7 + ["uncertain"] * 5  # grouping put 7 direct papers elsewhere
    plan = assign_roles(ps, blocks(4, 12), question, relevance, Settings())
    assert len(plan.main) == 10 and "6 more papers judged directly relevant" in plan.main_reason


def test_small_side_groups_merge_into_their_nearest_group():
    ps = papers(17)
    sim = blocks(5, 3, 4, 4, 1, across=.1)
    sim[16, 8:12] = sim[8:12, 16] = .6  # the singleton is closest to the 4-paper group
    question = np.r_[np.full(5, .9), np.full(12, .2)]
    plan = assign_roles(ps, sim, question, ["uncertain"] * 17, Settings())
    sides = sorted(map(sorted, plan.sides))
    assert all(len(g) >= 3 for g in sides) and any(16 in g and 8 in g for g in sides)
    assert any(d["step"] == "side groups" and d["paper_ids"] == ["P16"] for d in plan.decisions)


def test_the_llm_relevance_check_decides_what_is_on_topic_for_foundation():
    # Real run, 26 Oct: retrieval keeps only papers above the question gate, so the gate cannot tell a protein
    # review (0.54, judged "uncertain") from on-topic work; the LLM check can.
    ps = papers(12, P05={"year": 2001, "citation_count": 900}, P06={"year": 2015, "citation_count": 40})
    question = np.r_[np.full(5, .9), np.full(7, .6)]
    relevance = ["direct"] * 5 + ["uncertain", "supporting"] + ["supporting"] * 5
    plan = assign_roles(ps, blocks(5, 7), question, relevance, Settings())
    assert "P05" not in [ps[i].id for i in plan.foundation] and ps[plan.foundation[0]].id == "P06"
