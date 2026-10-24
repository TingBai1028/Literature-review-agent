"""Programmatic interface: POST /run takes JSON and returns JSON.

Request:  {"run_id": optional str, "input": {"query": str, "effort": "normal|medium|high|ultra",
           "feedback": optional str, "signed_in": optional bool}}
Success:  {"run_id": ..., "status": "success", "output": {...RunResult fields...}}
Failure:  {"run_id": ..., "status": "error", "error": {"type": ..., "message": ...}}

GET /world/{run_id} returns a run's saved Meterless World Model: entities, relationships, facts,
the merge review queue and the audit log.

Human reviews never wait for input here: both are approved, unless `feedback` is given,
in which case Human review 1 sends it back to the Planner once (see RequestReviewer).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from litagent.config import Effort, Settings
from litagent.human_review import RequestReviewer
from litagent.integrations.meterless import load_world
from litagent.orchestrator import run_pipeline
from litagent.trace import mask, new_run_id, setup_logging

setup_logging()
app = FastAPI(title="Literature review agent")


class RunInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str
    effort: Effort = Effort.NORMAL
    feedback: str | None = None  # optional: triggers one re-plan at Human review 1
    signed_in: bool = False


RUN_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"  # run ids name files in logs/, so keep them to safe characters


class RunRequest(BaseModel):
    run_id: str | None = Field(default=None, pattern=RUN_ID_PATTERN)
    input: RunInput


def get_settings() -> Settings:
    return Settings()


def _error(run_id: str | None, status_code: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"run_id": run_id, "status": "error", "error": {"type": err_type, "message": mask(message)}},
    )


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = exc.body if isinstance(exc.body, dict) else {}
    run_id = body.get("run_id") if isinstance(body.get("run_id"), str) else None
    problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return _error(run_id, 422, "InvalidInput", problems)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.post("/run")
def run(req: RunRequest, settings: Settings = Depends(get_settings)) -> Any:
    run_id = req.run_id or new_run_id()
    try:
        result = run_pipeline(
            req.input.query,
            req.input.effort,
            RequestReviewer(req.input.feedback),
            settings,
            signed_in=req.input.signed_in,
            run_id=run_id,
        )
    except Exception as e:  # the trace already has the error and the failing stage
        return _error(run_id, 500, type(e).__name__, str(e))
    return {"run_id": run_id, "status": "success", "output": result.model_dump(mode="json")}


@app.get("/world/{run_id}")
def world(run_id: str, settings: Settings = Depends(get_settings)) -> Any:
    if not re.fullmatch(RUN_ID_PATTERN, run_id):
        return _error(None, 422, "InvalidInput", "run_id may only contain letters, digits, '.', '_' and '-'")
    model = load_world(run_id, settings.logs_dir)
    if model is None:
        return _error(run_id, 404, "NotFound", f"No World Model saved for run {run_id}")
    shape = model.state_shape()
    return {"run_id": run_id, "status": "success", "output": {
        "entities": shape["entities"], "contexts": shape["contexts"], "relationships": shape["relationships"],
        "facts": shape["facts"], "merge_queue": model.merge_queue(), "audit": model.audit(), "events": len(model.events()),
    }}
