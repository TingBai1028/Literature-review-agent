"""Test doubles shared by several test files."""

from types import SimpleNamespace


class FakeClient:
    """Stands in for the OpenAI client: returns the given replies in order and records each request."""

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
