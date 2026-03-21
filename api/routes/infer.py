from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agents import RouterAgent

router = APIRouter()


class InferRequest(BaseModel):
    input: str


class InferResponse(BaseModel):
    task_type: str
    model_used: str
    router_confidence: float | None = None
    router_reasoning: str | None = None
    success: bool
    data: dict | None = None
    error: str | None = None
    retry_count: int
    ttft_ms: float | None = None
    tokens_per_sec: float | None = None
    total_ms: float | None = None
    routing_ms: float | None = None


@router.post("/infer", response_model=InferResponse)
async def infer(request: InferRequest):
    if not request.input or not request.input.strip():
        raise HTTPException(status_code=422, detail="input cannot be empty")

    # RouterAgent handles classification + dispatch internally
    agent = RouterAgent()
    result = await run_in_threadpool(agent.run, user_input=request.input)

    if not result.success:
        status = 502 if result.task_type is None else 500
        detail = (
            f"Router failed to classify input: {result.error}"
            if result.task_type is None
            else f"Specialized agent failed for {result.task_type}: {result.error}"
        )
        raise HTTPException(status_code=status, detail=detail)

    return InferResponse(
        task_type=result.task_type,
        model_used=result.model_used,
        router_confidence=result.confidence,
        router_reasoning=result.reasoning,
        success=result.success,
        data=result.result.data if result.result else None,
        error=result.error,
        retry_count=result.result.retry_count if result.result else 0,
        ttft_ms=result.result.ttft_ms if result.result else None,
        tokens_per_sec=result.result.tokens_per_sec if result.result else None,
        total_ms=result.result.total_ms if result.result else None,
        routing_ms=result.routing_ms,
    )
