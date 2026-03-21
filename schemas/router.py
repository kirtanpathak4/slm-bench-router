from typing import Literal
from pydantic import BaseModel, Field


class RouterDecision(BaseModel):
    task_type: Literal["code_review", "log_classify", "doc_extract"]
    reasoning: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
