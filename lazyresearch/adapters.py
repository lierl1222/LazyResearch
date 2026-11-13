from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .models import Candidate, Evidence, Plan, ResearchTask, Result, Revision, Validation

Tool = Callable[[dict[str, Any], float, str], dict[str, Any]]


class ResearchAdapter(Protocol):
    tools: Mapping[str, Tool]

    def validate(self, task: ResearchTask) -> None: ...
    def plan(self, task: ResearchTask) -> Plan: ...
    def collect(self, task: ResearchTask, plan: Plan) -> list[Evidence]: ...
    def propose(self, evidence: list[Evidence], revision: Revision | None) -> list[Candidate]: ...
    def verify(self, results: list[Result], previous: Validation | None) -> Validation: ...
    def revise(self, validation: Validation, evidence: list[Evidence]) -> Revision: ...


class FixtureAdapter:
    def __init__(self):
        self.tools = {"fixture": self.execute}

    def validate(self, task: ResearchTask) -> None:
        if any(not resource for resource in task.resources):
            raise ValueError("资源引用不能为空")

    def plan(self, task: ResearchTask) -> Plan:
        return Plan(summary="运行确定性候选，依据验证反馈修正一次。")

    def collect(self, task: ResearchTask, plan: Plan) -> list[Evidence]:
        return [Evidence(id="fixture-input", summary="测试适配器提供初始证据。")]

    def propose(self, evidence: list[Evidence], revision: Revision | None) -> list[Candidate]:
        options = [("revised", "修正后满足验证条件", True)] if revision else [
            ("initial", "初始候选满足验证条件", True),
            ("failure", "独立候选可成功执行", False),
        ]
        references = revision.evidence_ids if revision else [evidence[0].id]
        return [
            Candidate(id=name, hypothesis=label, evidence_ids=references,
                      tool="fixture", parameters={"succeed": succeeds, "accepted": name == "revised"},
                      independent=True)
            for name, label, succeeds in options
        ]

    @staticmethod
    def execute(parameters: dict, timeout: float, operation_id: str) -> dict:
        if not parameters["succeed"]:
            raise ValueError("测试适配器模拟分支失败")
        return {"accepted": parameters["accepted"]}

    def verify(self, results: list[Result], previous: Validation | None) -> Validation:
        passed = any(result.data.get("accepted") for result in results)
        return Validation(summary="通过验证" if passed else "当前候选未通过验证",
                          passed=passed, improved=passed)

    def revise(self, validation: Validation, evidence: list[Evidence]) -> Revision:
        return Revision(summary="依据首轮验证结果，改用修正候选。",
                        evidence_ids=[item.id for item in evidence if item.id.startswith("result-")])
