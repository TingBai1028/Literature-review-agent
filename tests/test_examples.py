"""Each file in input_examples/ still produces the matching file in output_examples/ (sample mode).

Regenerate the outputs after an intended change: start `SAMPLE_MODE=true python run.py` and
curl each input (see README, "Examples").
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from litagent import api
from litagent.config import Settings

ROOT = Path(__file__).resolve().parents[1]
INPUTS = sorted((ROOT / "input_examples").glob("*.json"))


def without_plan(body: dict) -> dict:
    """The plan's default year_from depends on today's date, so compare it separately."""
    body = json.loads(json.dumps(body))
    plan = body.get("output", {}).pop("plan", None)
    return body, plan


def test_at_least_three_examples():
    assert len(INPUTS) >= 3
    assert all((ROOT / "output_examples" / f.name).exists() for f in INPUTS)


@pytest.mark.parametrize("input_file", INPUTS, ids=lambda f: f.stem)
def test_example_output_matches(input_file, tmp_path):
    settings = Settings()
    settings.sample_mode = True
    settings.logs_dir = str(tmp_path)
    api.app.dependency_overrides[api.get_settings] = lambda: settings
    try:
        r = TestClient(api.app).post("/run", json=json.loads(input_file.read_text(encoding="utf-8")))
    finally:
        api.app.dependency_overrides.clear()

    expected = json.loads((ROOT / "output_examples" / input_file.name).read_text(encoding="utf-8"))
    got_body, got_plan = without_plan(r.json())
    exp_body, exp_plan = without_plan(expected)
    assert got_body == exp_body
    if exp_plan:
        assert got_plan["question"] == exp_plan["question"]
        assert got_plan["max_papers"] == exp_plan["max_papers"]
