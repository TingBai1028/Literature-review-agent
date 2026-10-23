"""Programmatic interface: POST /run takes JSON and returns JSON.

Request:  {"run_id": optional str, "input": {"query": str, "effort": "normal|medium|high|ultra",
           "feedback": optional str, "signed_in": optional bool}}
Success:  {"run_id": ..., "status": "success", "output": {...RunResult fields...}}
Failure:  {"run_id": ..., "status": "error", "error": {"type": ..., "message": ...}}

Human reviews never wait for input here: both are approved, unless `feedback` is given,
in which case Human review 1 sends it back to the Planner once (see RequestReviewer).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from litagent.config import Effort, Settings
from litagent.human_review import RequestReviewer
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


class RunRequest(BaseModel):
    # Used in the trace file name, so keep it to safe characters
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")
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
