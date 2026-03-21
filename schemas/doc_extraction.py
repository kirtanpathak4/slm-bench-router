from typing import Annotated
from pydantic import BaseModel, Field

NonEmptyStr = Annotated[str, Field(min_length=1)]


class DocumentMetadata(BaseModel):
    title: str | None = Field(default=None, min_length=1)  # None = not found, but rejects empty ""
    parties: list[NonEmptyStr] = Field(default_factory=list)
    dates: list[NonEmptyStr] = Field(default_factory=list)
    key_obligations: list[NonEmptyStr] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
