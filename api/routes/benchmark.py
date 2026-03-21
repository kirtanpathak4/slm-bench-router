from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agents import CodeReviewAgent, DocExtractorAgent, LogClassifierAgent
from config import MODELS

router = APIRouter()

AGENT_MAP = {
    "log_classify": LogClassifierAgent,
    "code_review": CodeReviewAgent,
    "doc_extract": DocExtractorAgent,
}


class BenchmarkRequest(BaseModel):
    task: str
    model: str
    input: str


class BenchmarkResponse(BaseModel):
    task: str
    model: str
    success: bool
    data: dict | None = None
    error: str | None = None
    retry_count: int
    ttft_ms: float | None = None
    tokens_per_sec: float | None = None
    total_ms: float | None = None


@router.post("/benchmark", response_model=BenchmarkResponse)
async def benchmark(request: BenchmarkRequest):
    if request.task not in AGENT_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown task: {request.task}. Must be one of {list(AGENT_MAP.keys())}",
        )
    if request.model not in MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model: {request.model}. Must be one of {list(MODELS)}",
        )
    if not request.input or not request.input.strip():
        raise HTTPException(status_code=422, detail="input cannot be empty")

    agent_cls = AGENT_MAP[request.task]
    agent = agent_cls(model=request.model)
    result = await run_in_threadpool(agent.run, user_input=request.input)

    return BenchmarkResponse(
        task=request.task,
        model=request.model,
        success=result.success,
        data=result.data,
        error=result.error,
        retry_count=result.retry_count,
        ttft_ms=result.ttft_ms,
        tokens_per_sec=result.tokens_per_sec,
        total_ms=result.total_ms,
    )
