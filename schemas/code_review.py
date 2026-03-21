from typing import Literal
from pydantic import BaseModel, Field


class CodeReviewResult(BaseModel):
    issue_type: Literal["bug", "security", "performance", "style", "logic"]
    severity: Literal["low", "medium", "high", "critical"]
    line_number: int | None = Field(default=None, ge=1)
    suggestion: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
