"""complete_json with the OpenAI client mocked: never calls Nightshift in tests."""

import json
from types import SimpleNamespace

import pytest

from litagent.config import Settings
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, TokenMeter, complete_json
from litagent.schemas import HumanFeedback
from litagent.trace import Trace


class FakeClient:
    def __init__(self, replies, report_usage=True):
        self.replies = list(replies)
        self.report_usage = report_usage
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            model="nvidia/nemotron-test",
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5) if self.report_usage else None,
        )


def real_settings() -> Settings:
    s = Settings()
    s.sample_mode = False
    s.llm_model = "nvidia/nemotron-test"
    return s


def test_valid_json_is_parsed_and_logged(tmp_path):
    client = FakeClient(['{"approved": true}'])
    with Trace(str(tmp_path)) as trace:
        out = complete_json("sys", "user", HumanFeedback, settings=real_settings(), agent_name="planner", client=client)
    assert out == HumanFeedback(approved=True)
    assert client.calls[0]["model"] == "nvidia/nemotron-test"
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    [event] = trace.events
    assert event["agent_name"] == "planner"
    assert event["model"] == "nvidia/nemotron-test"
    assert event["tokens"] == {"prompt": 10, "completion": 5}


def test_retries_once_with_validation_error():
    client = FakeClient(['{"approved": "maybe"}', '```json\n{"approved": false, "comment": "x"}\n```'])
    out = complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert out == HumanFeedback(approved=False, comment="x")
    retry_messages = client.calls[1]["messages"]
    assert "did not validate" in retry_messages[-1]["content"]


@pytest.mark.parametrize("reply", [
    '<think>The user wants approval. {"approved": false}</think>\n{"approved": true}',
    'Reasoning without an opening tag...</think>{"approved": true}',
])
def test_reasoning_text_is_removed_before_parsing(reply):
    client = FakeClient([reply])
    out = complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert out == HumanFeedback(approved=True)
    assert len(client.calls) == 1  # parsed first time, no retry needed


def test_gives_up_after_second_invalid_reply():
    client = FakeClient(["not json", json.dumps({"approved": "maybe"})])
    with pytest.raises(LLMError):
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)


def test_refuses_in_sample_mode_and_without_model():
    s = real_settings()
    s.sample_mode = True
    with pytest.raises(LLMError):
        complete_json("sys", "user", HumanFeedback, settings=s, client=FakeClient([]))
    s = real_settings()
    s.llm_model = "TODO-nemotron-model-id"
    with pytest.raises(LLMError):
        complete_json("sys", "user", HumanFeedback, settings=s, client=FakeClient([]))


def test_meter_counts_every_attempt_including_retries():
    client = FakeClient(['{"approved": "maybe"}', '{"approved": true}'])
    with TokenMeter(budget=1000) as meter:
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert meter.usage.llm_calls == 2
    assert (meter.usage.prompt_tokens, meter.usage.completion_tokens) == (20, 10)
    assert meter.usage.estimated_calls == 0


def test_tokens_are_estimated_when_provider_reports_none(tmp_path):
    client = FakeClient(['{"approved": true}'], report_usage=False)
    with Trace(str(tmp_path)) as trace, TokenMeter() as meter:
        complete_json("sys", "user " * 100, HumanFeedback, settings=real_settings(), client=client)
    assert meter.usage.estimated_calls == 1
    assert meter.usage.prompt_tokens > 100  # schema + 500 characters of user message, at ~4 characters per token
    assert trace.events[-1]["tokens"]["estimated"] is True


def test_no_call_once_budget_is_used_up():
    client = FakeClient(['{"approved": true}'])
    with TokenMeter(budget=100) as meter:
        meter.add(80, 20)
        with pytest.raises(TokenBudgetExceeded):
            complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert client.calls == []
