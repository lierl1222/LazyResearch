from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Budget(Record):
    rounds: int = Field(default=3, ge=1, le=100)
    tools: int = Field(default=6, ge=0, le=200)
    cloud_requests: int = Field(default=0, ge=0, le=100)
    tokens: int = Field(default=0, ge=0)
    seconds: float = Field(default=120, gt=0, le=86400)


class ResearchTask(Record):
    goal: str = Field(min_length=1, max_length=2000)
    resources: list[str] = Field(default_factory=list, max_length=30)
    adapter_id: str = "fixture"
    budget: Budget = Field(default_factory=Budget)


class Evidence(Record):
    id: str
    summary: str
    artifact: str | None = None


class Plan(Record):
    summary: str
    needs_help: bool = False


class Candidate(Record):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    hypothesis: str
    evidence_ids: list[str]
    tool: str
    parameters: dict[str, Any]
    independent: bool = False


class Result(Record):
    candidate_id: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    artifact: str


class Validation(Record):
    summary: str
    passed: bool
    improved: bool
    recoverable_unknown: bool = False


class Revision(Record):
    summary: str
    evidence_ids: list[str] = Field(min_length=1)
