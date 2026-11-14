from pydantic import Field

from ..models import Record


class Polynomial(Record):
    coefficients: list[int] = Field(min_length=1, max_length=12)


def sequence(root, task, args):
    values = task["sequence"]
    for n, observed in enumerate(values):
        predicted = sum(c * n**k for k, c in enumerate(args.coefficients))
        if predicted != observed:
            return {"verdict": "refuted", "n": n, "expected": observed, "actual": predicted}
    return {"verdict": "supported", "scope": "supplied indices only", "samples": len(values)}


class SuppliedPolynomial(Polynomial):
    values: list[int] = Field(min_length=1, max_length=256)


def supplied_sequence(root, task, args):
    return sequence(root, {"sequence": args.values}, args)
