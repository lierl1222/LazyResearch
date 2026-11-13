from typing import Literal, Protocol

from pydantic import Field

from .models import Record


class Decision(Record):
    action_id: str
    usage: int | None = Field(default=None, ge=0)


class ModelGateway(Protocol):
    def reserve(self, prompt: str, context: dict) -> int:
        """Return a conservative bound for input and enforced output tokens."""
        ...

    def decide(self, prompt: str, context: dict, timeout: float, request_id: str) -> Decision:
        """Return one offered action ID and total provider usage, if known."""
        ...


class Prompts(Record):
    planning: str = ""
    diagnosis: str = ""


Role = Literal["planning", "diagnosis"]
