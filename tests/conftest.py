"""Shared test guards."""

import pytest

from litagent.integrations import llm


@pytest.fixture(autouse=True)
def no_real_model_calls(monkeypatch):
    """Tests never reach Nightshift: .env may hold real credentials, and a call without a mock would spend tokens.
    Tests that need a model pass a fake client or mock complete_json in the module under test."""
    def refuse(settings):
        raise llm.LLMError("Tests must not call the real model; mock complete_json or pass a fake client")
    monkeypatch.setattr(llm, "get_client", refuse)
