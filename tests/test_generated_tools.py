from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.registry import Registry


def test_worker_repairs_registers_and_calls_new_tool(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对函数结果', limitations='样例不能代替研究', next_step='用真实输入测试', action='validate')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="no matching numeric function",tools=[])
            if schema.__name__ == "Direction":
                done = bool(context["observations"])
                return schema(action="finish" if done else "delegate", objective_or_conclusion="double",
                              evidence=["worker-0-2"] if done else [])
            args = {"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                    "source":"x=>x.n+1" if "0-0-" in id else "x=>x.n*2"}
            tool = "register_tool"
            if "0-2-" in id:
                assert "custom_double" in context["tools"]
                tool,args = "custom_double",{"inputs":{"n":11}}
            return schema(action="experiment",tool=tool,arguments=args,hypothesis_or_finding="double",
                          prediction_or_limitation="matches test input")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=3)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert "error" in observations["worker-0-0"]
    assert observations["worker-0-1"]["registered"] == "custom_double"
    assert observations["worker-0-2"]["value"] == 22
    assert registry.get("generated_tools","custom_double")["source"] == "x=>x.n*2"

