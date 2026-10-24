"""FastAPI app: `uv run uvicorn app.api.main:app --port 8000` (jobs in JOBS_DIR, out/jobs)."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.jobs import router
from app.api.worker import JobRunner, Pipeline, default_pipeline

ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def create_app(root: Path | None = None, pipeline: Pipeline = default_pipeline) -> FastAPI:
    jobs_dir = root or Path(os.environ.get("JOBS_DIR", "out/jobs"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runner = JobRunner(jobs_dir, pipeline)
        yield
        app.state.runner.stop()

    app = FastAPI(title="Short Video AI", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        where = "; ".join(".".join(str(p) for p in e["loc"][1:]) or "dữ liệu" for e in exc.errors())
        return JSONResponse(
            status_code=422, content={"detail": f"Dữ liệu gửi lên không hợp lệ ({where})"}
        )

    app.include_router(router)
    return app


app = create_app()
