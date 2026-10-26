"""Live progress events (spec A1, B2, B3): trace lines served as a server-sent event stream."""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from litagent import api
from litagent.config import Effort, Settings
from litagent.events import stream_events, to_event
from litagent.human_review import AutoApproveReviewer
from litagent.orchestrator import run_pipeline
from litagent.trace import Trace

KEYS = {"run_id", "seq", "ts", "agent", "phase", "message", "payload", "step", "step_kind", "decision", "result",
        "next", "why", "terminal"}


def parse(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def test_trace_lines_carry_phase_step_kind_message_and_whole_payloads(tmp_path):
    with Trace(str(tmp_path), "kinds") as trace:
        trace.log("clusterer", "group papers", "3 clusters", payload={"paper_ids": ["A", "B", "C"]}, phase="partial_result")
        trace.log("planner", "llm call SearchPlan", "valid JSON", model="nvidia/nemotron")
        trace.log("human", "review 1", "approved")
        trace.log("orchestrator", "finish", "done", phase="done", terminal=True)
    code, llm, human, end = trace.events
    assert code["step_kind"] == "code" and code["payload"] == {"paper_ids": ["A", "B", "C"]}  # not shortened to "3 items"
    assert code["message"] == "group papers: 3 clusters"
    assert llm["step_kind"] == "llm" and human["step_kind"] == "human" and end["terminal"] is True
    assert set(to_event(0, code)) == KEYS and to_event(3, end)["phase"] == "done"


def test_a_run_replays_as_an_event_stream_that_ends_at_its_terminal_event(tmp_path):
    settings = Settings(sample_mode=True, logs_dir=str(tmp_path))
    api.app.dependency_overrides[api.get_settings] = lambda: settings
    try:
        with TestClient(api.app) as client:
            papers = json.loads((Path(__file__).resolve().parents[1] / "data/sample/low_resource_languages_llm.json").read_text())[:30]
            client.post("/cluster", json={"run_id": "events-map", "input": {"query": "LLMs for low-resource languages",
                                                                             "papers": papers}})
            response = client.get("/runs/events-map/events")
            assert response.headers["content-type"].startswith("text/event-stream")
            events = parse(response.text)
            resumed = parse(client.get("/runs/events-map/events?after=3").text)
            assert client.get("/runs/bad!id/events").status_code == 422
    finally:
        api.app.dependency_overrides.clear()
    assert [e["seq"] for e in events] == list(range(len(events))) and all(set(e) == KEYS for e in events)
    assert events[-1]["terminal"] and events[-1]["phase"] == "done" and sum(e["terminal"] for e in events) == 1
    clusterer = [e["phase"] for e in events if e["agent"] == "clusterer"]
    assert clusterer[0] == "start" and "partial_result" in clusterer and "done" in clusterer
    grouped = next(e for e in events if e["step"] == "group papers")
    assert grouped["payload"]["clusters"][0]["kind"] == "main" and grouped["payload"]["clusters"][0]["paper_ids"]
    assert resumed[0]["seq"] == 4 and resumed == events[4:]


def test_stream_follows_a_run_that_starts_after_the_client_subscribes(tmp_path):
    path = tmp_path / "trace-live.jsonl"

    async def scenario():
        async def write():
            await asyncio.sleep(.1)
            with Trace(str(tmp_path), "live") as trace:
                trace.log("retriever", "start", "search", phase="start")
                await asyncio.sleep(.1)
                trace.log("retriever", "search openalex", "12 papers", phase="partial_result", payload={"papers_fetched": 12})
                await asyncio.sleep(.1)
                trace.log("orchestrator", "finish", "ok", phase="done", terminal=True)
        writer = asyncio.create_task(write())
        events = [json.loads(chunk.split("data: ", 1)[1]) async for chunk in stream_events(path, "live", poll_s=.02)]
        await writer
        return events
    events = asyncio.run(scenario())
    assert [e["phase"] for e in events] == ["start", "partial_result", "done"]
    assert events[1]["payload"] == {"papers_fetched": 12}


def test_stream_gives_up_with_an_error_when_the_run_never_starts(tmp_path):
    async def scenario():
        return [chunk async for chunk in stream_events(tmp_path / "trace-none.jsonl", "none", wait_s=.05, poll_s=.01)]
    (event,) = [json.loads(c.split("data: ", 1)[1]) for c in asyncio.run(scenario())]
    assert event["phase"] == "error" and event["terminal"] and "No run with ID none" in event["message"]


def test_every_agent_reports_its_start_and_end_with_labelled_steps(tmp_path):
    result = run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(),
                          Settings(sample_mode=True, logs_dir=str(tmp_path)))
    events = [json.loads(line) for line in (tmp_path / f"trace-{result.run_id}.jsonl").read_text().splitlines()]
    for agent in ("planner", "retriever", "clusterer", "connection_finder", "gap_finder"):
        phases = [e["phase"] for e in events if e["agent_name"] == agent]
        assert phases[0] == "start" and "done" in phases, agent
    assert all(e["step_kind"] in {"code", "llm", "human"} and e["message"] for e in events)
    assert events[-1]["terminal"] and events[-1]["action"] == "finish"
