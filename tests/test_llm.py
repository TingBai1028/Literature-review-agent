"""complete_json with the OpenAI client mocked: never calls Nightshift in tests."""

import json

import pytest

from litagent.config import Settings
from litagent.integrations.llm import LLMError, TokenBudgetExceeded, TokenMeter, complete_json
from litagent.integrations.llm import get_client as real_get_client  # bound before conftest blocks it
from litagent.schemas import HumanFeedback
from litagent.trace import Trace
from tests.fakes import FakeClient


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


def test_each_run_gets_its_own_nightshift_cache_partition(tmp_path):
    client = FakeClient(['{"approved": true}'])
    with Trace(str(tmp_path), run_id="run-42"):
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    headers = client.calls[0]["extra_headers"]
    assert headers["x-title"] == "litagent-run-42"
    assert headers["meterless-scope"].startswith("litagent-call-")


def test_every_call_and_json_repair_has_isolated_answer_memory():
    client = FakeClient(['not json', '{"approved": true}', '{"approved": false}'])
    for _ in range(2):
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    scopes = [call["extra_headers"]["meterless-scope"] for call in client.calls]
    assert len(scopes) == len(set(scopes)) == 3


def test_unexpected_memory_injection_is_rejected_and_logged(tmp_path):
    client = FakeClient(['{"approved": true}', '{"approved": true}'])
    client.receipt = {"scope": "ignored-scope", "receipt": {"hmem": {"injected": 2}}}
    with Trace(str(tmp_path)) as trace:
        with pytest.raises(LLMError, match="prior-answer memory"):
            complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert trace.events[-1]["nightshift_memory"]["injected"] == 2
    assert [e["next"] for e in trace.events] == ["discard and ask again in a new scope", "raise"]


def test_answer_built_from_injected_memory_is_discarded_and_asked_again(tmp_path):
    client = FakeClient(['{"approved": false}', '{"approved": true}'])
    client.receipt = [{"receipt": {"hmem": {"injected": 1}}}, {"receipt": {"hmem": {"injected": 0}}}]
    with Trace(str(tmp_path)) as trace, TokenMeter() as meter:
        out = complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert out == HumanFeedback(approved=True)
    scopes = [call["extra_headers"]["meterless-scope"] for call in client.calls]
    assert len(set(scopes)) == 2 and meter.usage.llm_calls == 2
    assert client.calls[1]["messages"] == client.calls[0]["messages"]  # the discarded answer is never shown again
    assert [e["decision"] for e in trace.events] == ["unexpected answer memory", "valid JSON"]


def test_gateway_scope_mismatch_is_rejected_even_with_no_retrieval():
    client = FakeClient(['{"approved": true}'])
    client.receipt = {"scope": "user", "receipt": {"hmem": None}}
    with pytest.raises(LLMError, match="did not honor"):
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)


def test_nightshift_cache_status_is_logged(tmp_path):
    client = FakeClient(['{"approved": true}'])
    client.receipt = {"cache": {"status": "exact"}}
    with Trace(str(tmp_path)) as trace:
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    assert trace.events[-1]["nightshift_cache"] == "exact"


@pytest.mark.parametrize("reply", [
    '{"gap_id": "G1", "label": "novel", "reason": "Nothing combines them."}',
    '[{"gap_id": "G1", "label": "novel", "reason": "Nothing combines them."}]',
])
def test_bare_item_of_a_one_list_schema_is_wrapped_without_a_retry(reply, tmp_path):
    from litagent.schemas import GapLabelDecisions  # real run 27 Oct: a one-gap batch came back without {"labels": [...]}
    client = FakeClient([reply])
    with Trace(str(tmp_path)) as trace:
        out = complete_json("sys", "user", GapLabelDecisions, settings=real_settings(), client=client)
    assert [(d.gap_id, d.label) for d in out.labels] == [("G1", "novel")] and len(client.calls) == 1
    assert trace.events[-1]["decision"] == "valid JSON after wrapping"


def test_echoed_request_is_not_wrapped():
    from litagent.schemas import GapLabelDecisions
    echo = json.dumps({"task_version": "gap-grader-v1", "gaps": [{"gap_id": "G1", "claim": "x"}]})
    client = FakeClient([echo, echo])
    with pytest.raises(LLMError):
        complete_json("sys", "user", GapLabelDecisions, settings=real_settings(), client=client)
    assert len(client.calls) == 2


def _timeout():
    import httpx
    from openai import APITimeoutError
    return APITimeoutError(request=httpx.Request("POST", "http://nightshift.test/v1/chat/completions"))


class FailingClient(FakeClient):
    """Raises the given errors first, then answers like FakeClient."""

    def __init__(self, errors, replies):
        super().__init__(replies)
        self.errors = list(errors)

    def create(self, **kwargs):
        if self.errors:
            self.calls.append(kwargs)
            raise self.errors.pop(0)
        return super().create(**kwargs)


def test_a_timeout_is_sent_again_once_only_for_callers_without_a_fallback(tmp_path):
    from openai import APITimeoutError
    client = FailingClient([_timeout()], ['{"approved": true}'])
    with Trace(str(tmp_path)) as trace:
        assert complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client).approved
    assert len(client.calls) == 2
    assert [e["decision"] for e in trace.events][:1] == ["timeout"] and trace.events[0]["next"] == "send again"
    client = FailingClient([_timeout()], ['{"approved": true}'])
    with pytest.raises(APITimeoutError):
        complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client, retry_timeout=False)
    assert len(client.calls) == 1  # the caller's fallback takes over after one llm_timeout_s, not two


def test_a_dropped_connection_is_sent_again_even_without_timeout_retry():
    import httpx
    from openai import APIConnectionError
    error = APIConnectionError(request=httpx.Request("POST", "http://nightshift.test/v1/chat/completions"))
    client = FailingClient([error], ['{"approved": true}'])
    assert complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client, retry_timeout=False).approved
    assert len(client.calls) == 2


def test_the_client_itself_never_retries(monkeypatch):
    monkeypatch.setenv("METERLESS_BASE_URL", "http://nightshift.test/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "test")
    assert real_get_client(real_settings()).max_retries == 0  # builds the client only; sends nothing


def test_a_timed_out_batch_is_asked_again_in_two_halves(tmp_path):
    from litagent.integrations.llm import halve_on_timeout
    asked = []
    def ask(items):
        asked.append(list(items))
        if len(items) > 2:
            raise LLMError("gap_finder provider request failed") from _timeout()
        return [i * 10 for i in items]
    with Trace(str(tmp_path)) as trace:
        assert halve_on_timeout(ask, [1, 2, 3, 4]) == ([10, 20, 30, 40], [], None)
    assert asked == [[1, 2, 3, 4], [1, 2], [3, 4]]
    assert any(e["action"] == "batch timed out" for e in trace.events)


def test_halves_that_still_fail_are_returned_and_other_errors_are_not_split():
    from litagent.integrations.llm import halve_on_timeout
    def ask(items):
        if 4 in items:
            raise _timeout()
        return items
    results, failed, error = halve_on_timeout(ask, [1, 2, 3, 4])
    assert results == [1, 2] and failed == [3, 4] and type(error).__name__ == "APITimeoutError"
    calls = []
    def invalid(items):
        calls.append(items)
        raise LLMError("failed validation twice")
    results, failed, error = halve_on_timeout(invalid, [1, 2])
    assert results == [] and failed == [1, 2] and isinstance(error, LLMError)
    assert len(calls) == 1  # only a timeout is split
    def broke(items):
        raise TokenBudgetExceeded("Finding analysis time limit reached")
    with pytest.raises(TokenBudgetExceeded):
        halve_on_timeout(broke, [1, 2])


ECHO_REQUEST = json.dumps({"question": "When can we avoid mean-cycle calculations?", "current_year": 2026, "number_of_queries": 3})


def test_an_answer_that_repeats_the_input_is_sent_again_unchanged(tmp_path):
    echo = json.dumps({"question": "When can we avoid mean-cycle calculations?", "current_year": 2026, "number_of_queries": 3})
    client = FakeClient([echo, '{"approved": true}'])
    with Trace(str(tmp_path)) as trace:
        assert complete_json("sys", ECHO_REQUEST, HumanFeedback, settings=real_settings(), client=client).approved
    assert client.calls[1]["messages"] == client.calls[0]["messages"]  # no repair turn quoting the echo
    assert trace.events[0]["decision"] == "answer repeated the input"


def test_repeated_echoes_fall_back_to_the_repair_turn_and_then_fail():
    echo = json.dumps({"question": "When can we avoid mean-cycle calculations?"})
    client = FakeClient([echo] * 4)
    with pytest.raises(LLMError):
        complete_json("sys", ECHO_REQUEST, HumanFeedback, settings=real_settings(), client=client)
    assert len(client.calls) == real_settings().llm_echo_retries + 2  # resends, then one repair turn
    assert "did not validate" in client.calls[-1]["messages"][-1]["content"]


def test_an_invalid_answer_with_its_own_fields_is_not_an_echo():
    client = FakeClient(['{"approved": "maybe"}', '{"approved": false}'])
    complete_json("sys", ECHO_REQUEST, HumanFeedback, settings=real_settings(), client=client)
    assert "did not validate" in client.calls[1]["messages"][-1]["content"]


def test_the_system_message_says_not_to_repeat_the_input():
    client = FakeClient(['{"approved": true}'])
    complete_json("sys", "user", HumanFeedback, settings=real_settings(), client=client)
    system = client.calls[0]["messages"][0]["content"]
    assert system.endswith('Reply with the output object only (its first key is "approved"); never repeat the input.')
