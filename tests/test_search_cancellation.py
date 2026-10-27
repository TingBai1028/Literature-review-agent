"""Search cancellation stops work at safe boundaries without affecting other requests."""
import asyncio
import json
import time
from threading import Event
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from openai import APIConnectionError

from litagent import api, search_review
from litagent.agents import retriever
from litagent.cancellation import SearchCancelled, cancellation_scope, check_cancelled
from litagent.config import Effort, Settings
from litagent.integrations import embeddings, llm
from litagent.schemas import SearchCriteria, SearchPlan
from tests.test_embeddings import Encoder


def test_cancellation_scope_does_not_leak_to_other_requests():
    stop = Event()
    stop.set()
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        check_cancelled()
    check_cancelled()
    with cancellation_scope(Event()):
        check_cancelled()


def test_cancel_after_a_source_returns_skips_remaining_sources_and_ranking(monkeypatch):
    stop, calls = Event(), []
    plan = SearchPlan(question="language models", criteria=SearchCriteria(topic="language models"),
                      queries=["language models", "language adaptation"], effort=Effort.FAST, token_budget=350000,
                      max_papers=50, retrieval_target=300)
    def first(*args, **kwargs):
        calls.append("openalex")
        stop.set()
        return retriever._fake_papers(1)
    monkeypatch.setattr(retriever, "search_openalex", first)
    monkeypatch.setattr(retriever, "search_arxiv", lambda *a, **kw: pytest.fail("started another provider after cancel"))
    monkeypatch.setattr(retriever, "apply_relevance_floor", lambda *a: pytest.fail("ranked cancelled results"))
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        retriever.retrieve_pool(plan, Settings(sample_mode=False, retrieval_sources=("openalex", "arxiv")))
    assert calls == ["openalex"]


def test_cancelled_plan_never_starts_retrieval_and_logs_a_terminal_cancel(monkeypatch, tmp_path):
    cfg = Settings(sample_mode=True, logs_dir=str(tmp_path))
    planned = search_review.planner.plan("language models for translation", Effort.FAST, cfg)
    stop = Event()
    def plan(*args):
        stop.set()
        return planned
    monkeypatch.setattr(search_review.planner, "plan", plan)
    monkeypatch.setattr(retriever, "retrieve_pool", lambda *a, **kw: pytest.fail("retrieval started after cancel"))
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        search_review.run_search("language models for translation", Effort.FAST, cfg, search_id="cancel-plan")
    events = [json.loads(row) for row in (tmp_path / "trace-cancel-plan.jsonl").read_text().splitlines()]
    assert events[-1]["terminal"] and events[-1]["decision"] == "cancelled"
    assert not any(e["action"] == "finish search review" for e in events)


def test_http_disconnect_signals_the_search_worker(monkeypatch, tmp_path):
    started, finished = Event(), Event()
    def searching(*args, **kwargs):
        started.set()
        try:
            for _ in range(200):
                check_cancelled()
                time.sleep(.01)
            pytest.fail("disconnect did not cancel the worker")
        finally:
            finished.set()
    class DisconnectedRequest:
        async def is_disconnected(self):
            return started.is_set()
    monkeypatch.setattr(api, "run_search", searching)
    body = api.SearchRequest(run_id="cancel-http", input={"query": "language models"})
    response = asyncio.run(api.search(body, DisconnectedRequest(), Settings(logs_dir=str(tmp_path))))
    assert response.status_code == 499 and finished.is_set()
    assert json.loads(response.body)["error"]["type"] == "SearchCancelled"


def test_embedding_cancellation_stops_before_the_next_cpu_batch(monkeypatch):
    stop, calls = Event(), []
    encoder = Encoder()
    def encode(chunks, **kwargs):
        calls.append(list(chunks))
        stop.set()
        return Encoder.encode(encoder, chunks, **kwargs)
    encoder.encode = encode
    monkeypatch.setattr(embeddings, "_encoder", lambda path: encoder)
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        embeddings.embed_documents(["a b c d e f", "x y"], Settings(embedding_batch_size=1))
    assert calls == [["a b c d"]]


def test_cancellable_embedding_batches_preserve_document_pooling(monkeypatch):
    monkeypatch.setattr(embeddings, "_encoder", lambda path: Encoder())
    with cancellation_scope(Event()):
        result = embeddings.embed_documents(["a b c d e f", "x y"], Settings(embedding_batch_size=1))
    np.testing.assert_allclose(result, [[2 ** -.5, 2 ** -.5], [0, 1]], rtol=1e-6)


def test_provider_error_does_not_retry_after_cancellation():
    stop, calls = Event(), []
    def create(**kwargs):
        calls.append(kwargs)
        stop.set()
        raise APIConnectionError(request=httpx.Request("POST", "https://offline.invalid"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        llm._create(client, True, "planner", "plan", model="offline-model")
    assert len(calls) == 1


def test_cancel_after_storage_skips_the_summary(monkeypatch, tmp_path):
    cfg = Settings(sample_mode=True, logs_dir=str(tmp_path))
    stop = Event()
    def store(papers, *args):
        stop.set()
        return papers
    monkeypatch.setattr(search_review, "_through_zetaris", store)
    monkeypatch.setattr(retriever, "summarise", lambda *a: pytest.fail("summary started after cancel"))
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        search_review.run_search("language models for low-resource languages", Effort.FAST, cfg)


@pytest.mark.parametrize("provider", ["openalex", "arxiv", "semantic_scholar"])
def test_scholarly_provider_does_not_retry_after_cancel(monkeypatch, provider):
    from importlib import import_module
    module = import_module("litagent.tools." + provider)
    stop, calls = Event(), []
    def get(*args, **kwargs):
        calls.append(args)
        stop.set()
        raise httpx.ConnectError("Offline provider unavailable")
    monkeypatch.setattr(module.httpx, "get", get)
    if provider == "arxiv":
        monkeypatch.setattr(module, "_last_call", 0)
    with cancellation_scope(stop), pytest.raises(SearchCancelled):
        module.search_openalex("language models", SearchCriteria(topic="language models")) if provider == "openalex" else (
            getattr(module, "search_" + provider)("language models", SearchCriteria(topic="language models")))
    assert len(calls) == 1
