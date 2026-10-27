"""Make one tiny LLM call through Nightshift to check a configured model route.

    python scripts/check_nightshift.py
    python scripts/check_nightshift.py --grader

Needs METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN in .env, and the producer/checker
models in litagent/config.py. Prints the model that answered and the tokens used, and writes
a trace to logs/. Both commands make a real model request and may consume provider credit.
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grader", action="store_true", help="Check GRADER_MODEL instead of the producer model")
    args = parser.parse_args()
    settings = Settings()
    settings.sample_mode = False  # this script exists to call the real provider
    model = settings.grader_model if args.grader else settings.llm_model
    print(f"Requested model: {model}")
    try:
        with Trace(settings.logs_dir) as trace, TokenMeter() as meter:
            out = complete_json(
                "You check that a connection works.",
                'Return {"ok": true, "topic": "<one research topic in 3 words>"}.',
                Ping,
                model=model,
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
