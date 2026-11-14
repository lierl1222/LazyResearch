from unittest.mock import patch

from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.execution import execute_isolated as real_execute_isolated
from lazyresearch.science.registry import Registry


def test_blocked_tool_stays_blocked_across_delegations(tmp_path):
    def fake_execute(registry, budget, key, fn, payload):
        if payload.get("tool") == "sequence":
            return {"error": "boom"}
        return real_execute_isolated(registry, budget, key, fn, payload)

    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='失败', limitations='工具不匹配', next_step='编写自定义工具', action='revise')
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="fit polynomial")
            if "0-0-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [1, 0]},
                              hypothesis_or_finding="h", prediction_or_limitation="p")
            if "0-1-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [2, 0]},
                              hypothesis_or_finding="h", prediction_or_limitation="p")
            if "0-2-" in id:
                return schema(action="return", hypothesis_or_finding="stuck", prediction_or_limitation="sequence fails")
            if "1-0-" in id:
                assert "sequence" not in context["tools"]
                assert context["blocked_tools"] == ["sequence"]
                assert "register_tool" in instruction
                return schema(action="return", hypothesis_or_finding="blocked confirmed", prediction_or_limitation="none")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="none")

    registry = Registry(tmp_path)
    task = Task(goal="Infer polynomial", sequence=[1, 2, 5], max_delegations=2, max_worker_turns=3)
    budget = BudgetGovernor(registry, task.budget)
    with patch("lazyresearch.research.execute_isolated", fake_execute):
        result = research(task, task.model_dump(), registry, Gateway(), budget)
    assert "worker-0-0" in result["evidence"]
    assert result["status"] in {"reported", "inconclusive"}


def test_repeated_refuted_injects_tool_change_nudge(tmp_path):
    instructions = []

    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='未支持', limitations='区间有限', next_step='换系数或换工具', action='revise')
            if schema.__name__ == "Direction":
                if context.get("reports"):
                    return schema(action="finish", objective_or_conclusion="no fit", evidence=[])
                return schema(action="delegate", objective_or_conclusion="fit polynomial")
            if schema.__name__ == "Experiment":
                instructions.append(instruction)
            if "0-0-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [1, 0]},
                              hypothesis_or_finding="constant", prediction_or_limitation="fits")
            if "0-1-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [2, 0]},
                              hypothesis_or_finding="steeper", prediction_or_limitation="fits")
            return schema(action="return", hypothesis_or_finding="no fit", prediction_or_limitation="none")

    registry = Registry(tmp_path)
    task = Task(goal="Infer polynomial", sequence=[1, 2, 1], max_delegations=1, max_worker_turns=3)
    research(task, task.model_dump(), registry, Gateway(), BudgetGovernor(registry, task.budget))
    assert any("连续两次未支持假设" in text for text in instructions)


def test_unregistered_tool_error_lists_available_tools(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='未注册工具', limitations='需先注册', next_step='用 register_tool 注册', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="read materials", tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="read materials")
            if "0-0-" in id:
                return schema(action="experiment", tool="custom_nonexistent", arguments={"inputs": {}},
                              hypothesis_or_finding="h", prediction_or_limitation="p")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="none")

    registry = Registry(tmp_path)
    task = Task(goal="churn prediction", domain="数据分析", max_delegations=1, max_worker_turns=2)
    result = research(task, task.model_dump(), registry, Gateway(), BudgetGovernor(registry, task.budget))
    error = result["evidence"]["worker-0-0"]["error"]
    assert "可用工具" in error and "register_tool" in error


def test_duplicate_attempt_cites_previous_observation(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='有限', next_step='换参数', action='revise')
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="fit polynomial")
            if "0-0-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [1, 0]},
                              hypothesis_or_finding="h", prediction_or_limitation="p")
            if "0-1-" in id:
                return schema(action="experiment", tool="sequence", arguments={"coefficients": [1, 0]},
                              hypothesis_or_finding="h", prediction_or_limitation="p")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="none")

    registry = Registry(tmp_path)
    task = Task(goal="Infer polynomial", sequence=[1, 2, 5], max_delegations=1, max_worker_turns=3)
    result = research(task, task.model_dump(), registry, Gateway(), BudgetGovernor(registry, task.budget))
    error = result["evidence"]["worker-0-1"]["error"]
    assert "观测 worker-0-0" in error


def test_tabular_material_guard_swaps_domain_tools_for_table_tools(tmp_path):
    plan_contexts = []

    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == "CapabilityPlan":
                plan_contexts.append(context)
                return schema(objective="wrong plan", tools=["benchmark_membership"])
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='无数据', next_step='注册自定义工具', action='validate')
            if schema.__name__ == "Direction":
                return schema(action="finish", objective_or_conclusion="no data", evidence=[])
            if schema.__name__ == "Experiment":
                assert "uploaded_table" in context["tools"]
                assert "benchmark_membership" not in context["tools"]
                return schema(action="return", hypothesis_or_finding="guard ok", prediction_or_limitation="none")
            raise AssertionError(schema.__name__)

    registry = Registry(tmp_path)
    task = Task(goal="churn prediction", domain="数据分析")
    material = {**task.model_dump(), "csv_files": ["f1"]}
    research(task, material, registry, Gateway(), BudgetGovernor(registry, task.budget))
    assert "表格" in plan_contexts[0]["material_kinds"]
