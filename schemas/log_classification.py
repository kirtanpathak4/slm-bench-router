from typing import Literal
from pydantic import BaseModel, Field


class LogClassification(BaseModel):
    anomaly_type: Literal[
        "database", "network", "memory", "auth", "storage", "application"
    ]
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: str = Field(..., min_length=1)
