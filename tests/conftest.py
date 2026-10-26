"""Shared test guards."""

import pytest

from litagent.integrations import llm


@pytest.fixture(autouse=True)
def sequential_model_calls(monkeypatch):
    """Mocked models in most tests keep call-order state; tests of parallel calls set llm_concurrency themselves."""
    monkeypatch.setenv("LLM_CONCURRENCY", "1")


@pytest.fixture(autouse=True)
def private_search_cache(monkeypatch, tmp_path):
    """Each test gets its own scholarly search cache. The real data/cache/scholarly-search.sqlite3 holds live
    OpenAlex pages and daily-limit pauses (a real 429 on 27 Oct made a coverage test fail) and must not leak in."""
    monkeypatch.setenv("SCHOLARLY_SEARCH_DB", str(tmp_path / "scholarly-search.sqlite3"))


@pytest.fixture(autouse=True)
def no_real_model_calls(monkeypatch):
    """Tests never reach Nightshift: .env may hold real credentials, and a call without a mock would spend tokens.
    Tests that need a model pass a fake client or mock complete_json in the module under test."""
    def refuse(settings):
        raise llm.LLMError("Tests must not call the real model; mock complete_json or pass a fake client")
    monkeypatch.setattr(llm, "get_client", refuse)
