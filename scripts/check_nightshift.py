"""Make one tiny LLM call through Nightshift to check the connection and the model ID.

    python scripts/check_nightshift.py

Needs METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN in .env, and NIGHTSHIFT_MODEL in
litagent/config.py. Prints the model that answered and the tokens used, and writes a trace
to logs/ (its `model` field is the evidence that a Nemotron model handled the request).
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from litagent.config import Settings  # noqa: E402
from litagent.integrations.llm import TokenMeter, complete_json  # noqa: E402
from litagent.trace import Trace, mask  # noqa: E402


class Ping(BaseModel):
    ok: bool
    topic: str


def main() -> int:
    settings = Settings()
    settings.sample_mode = False  # this script exists to call the real provider
    print(f"Requested model: {settings.llm_model}")
    try:
        with Trace(settings.logs_dir) as trace, TokenMeter() as meter:
            out = complete_json(
                "You check that a connection works.",
                'Return {"ok": true, "topic": "<one research topic in 3 words>"}.',
                Ping,
                settings=settings,
                agent_name="check_nightshift",
            )
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {mask(str(e))}", file=sys.stderr)
        return 1

    u = meter.usage
    print(f"Answered by:     {trace.events[-1].get('model')}")
    print(f"Reply:           {out.model_dump()}")
    print(f"Tokens:          {u.prompt_tokens} prompt + {u.completion_tokens} completion in {u.llm_calls} call(s)"
          + (" (estimated)" if u.estimated_calls else ""))
    print(f"Trace:           {trace.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
