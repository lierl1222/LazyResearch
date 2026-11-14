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
    assert observations["worker-0-2"]["registration"] == "verified"
    assert registry.get("generated_tools","custom_double")["source"] == "x=>x.n*2"


def test_pending_tool_rejects_example_reuse_and_stays_unregistered(tmp_path):
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
                              evidence=["worker-0-1"] if done else [])
            if "0-1-" in id:
                assert "custom_double" in context["tools"]
                return schema(action="experiment", tool="custom_double", arguments={"inputs":{"n":2}},
                              hypothesis_or_finding="verify", prediction_or_limitation="same as example")
            return schema(action="experiment", tool="register_tool",
                          arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                     "source":"x=>x.n*2"},
                          hypothesis_or_finding="double", prediction_or_limitation="matches test input")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=3,max_delegations=2)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert "验证输入不能与注册样例相同" in observations["worker-0-1"]["error"]
    assert registry.get("generated_tools","custom_double") is None
    assert registry.get("pending_tools","custom_double")["status"] in {"pending","unverified"}
    assert any(item["name"] == "custom_double" for item in result.get("pending_tools", []))
    assert "custom_double" in result["summary"]


def test_pending_tool_discarded_after_repeated_failures(tmp_path):
    source = "x => { if (x.n === undefined) throw new Error('missing n'); return x.n*2 }"
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='函数在缺键时抛错', limitations='样例过于简单', next_step='重新注册稳健实现', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="no matching numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="verify custom tool")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_tricky","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":source},
                              hypothesis_or_finding="register", prediction_or_limitation="sample passes")
            if "0-1-" in id:
                return schema(action="experiment", tool="custom_tricky", arguments={"inputs":{"m":3}},
                              hypothesis_or_finding="verify", prediction_or_limitation="real input")
            if "0-2-" in id:
                return schema(action="experiment", tool="custom_tricky", arguments={"inputs":{"m":4}},
                              hypothesis_or_finding="retry", prediction_or_limitation="another input")
            assert "custom_tricky" not in context["tools"]
            return schema(action="return", hypothesis_or_finding="tool unusable",
                          prediction_or_limitation="throws for missing keys")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=4,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert observations["worker-0-1"]["pending_failures"] == 1
    assert observations["worker-0-2"]["registration"] == "discarded"
    assert registry.get("generated_tools","custom_tricky") is None
    assert registry.get("pending_tools","custom_tricky")["status"] == "discarded"


def test_pending_tool_re_registration_resets_failures_and_promotes(tmp_path):
    broken = "x => { if (x.n === undefined) throw new Error('missing n'); return x.n*2 }"
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='样例有限', next_step='修正后重试', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="verify custom tool")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":broken},
                              hypothesis_or_finding="register v1", prediction_or_limitation="sample passes")
            if "0-1-" in id:
                return schema(action="experiment", tool="custom_double", arguments={"inputs":{"m":3}},
                              hypothesis_or_finding="verify v1", prediction_or_limitation="fails")
            if "0-2-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":"x=>x.n*2"},
                              hypothesis_or_finding="register v2", prediction_or_limitation="corrected source")
            if "0-3-" in id:
                return schema(action="experiment", tool="custom_double", arguments={"inputs":{"n":11}},
                              hypothesis_or_finding="verify v2", prediction_or_limitation="real input")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="verified")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=5,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert observations["worker-0-1"]["pending_failures"] == 1
    assert observations["worker-0-2"]["registered"] == "custom_double"
    assert observations["worker-0-3"]["registration"] == "verified"
    assert observations["worker-0-3"]["value"] == 22
    assert registry.get("generated_tools","custom_double")["source"] == "x=>x.n*2"
    assert registry.get("pending_tools","custom_double")["status"] == "verified"


def test_verified_tool_blocked_after_two_failures(tmp_path):
    fragile = "x => { if (x.m !== undefined) throw new Error('m not supported'); return x.n*2 }"
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='样例有限', next_step='换输入或换工具', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="verify custom tool")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_fragile","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":fragile},
                              hypothesis_or_finding="register", prediction_or_limitation="sample passes")
            if "0-1-" in id:
                return schema(action="experiment", tool="custom_fragile", arguments={"inputs":{"n":5}},
                              hypothesis_or_finding="verify", prediction_or_limitation="real input")
            if "0-2-" in id:
                return schema(action="experiment", tool="custom_fragile", arguments={"inputs":{"m":1}},
                              hypothesis_or_finding="edge case", prediction_or_limitation="fails")
            if "0-3-" in id:
                return schema(action="experiment", tool="custom_fragile", arguments={"inputs":{"m":2}},
                              hypothesis_or_finding="edge case again", prediction_or_limitation="fails again")
            assert "custom_fragile" not in context["tools"]
            assert context["blocked_tools"] == ["custom_fragile"]
            return schema(action="return", hypothesis_or_finding="blocked confirmed", prediction_or_limitation="limitations")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=6,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert observations["worker-0-1"]["registration"] == "verified"
    assert observations["worker-0-1"]["value"] == 10
    assert "error" in observations["worker-0-2"] and "error" in observations["worker-0-3"]


def test_re_registration_after_discard_allows_original_input_retry(tmp_path):
    broken = "x => { if (x.n === undefined) throw new Error('missing n'); return x.n*2 }"
    fixed = "x => (x.n ?? 0) * 2"
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='样例有限', next_step='修正后重试原输入', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="verify custom tool")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_x","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":broken},
                              hypothesis_or_finding="register v1", prediction_or_limitation="sample passes")
            if "0-1-" in id:
                return schema(action="experiment", tool="custom_x", arguments={"inputs":{"m":3}},
                              hypothesis_or_finding="verify v1", prediction_or_limitation="fails")
            if "0-2-" in id:
                return schema(action="experiment", tool="custom_x", arguments={"inputs":{"m":4}},
                              hypothesis_or_finding="retry v1", prediction_or_limitation="fails again")
            if "0-3-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_x","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":fixed},
                              hypothesis_or_finding="register v2", prediction_or_limitation="corrected source")
            if "0-4-" in id:
                return schema(action="experiment", tool="custom_x", arguments={"inputs":{"m":3}},
                              hypothesis_or_finding="re-verify original input", prediction_or_limitation="should pass now")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="verified")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=6,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert observations["worker-0-2"]["registration"] == "discarded"
    assert observations["worker-0-3"]["registered"] == "custom_x"
    assert observations["worker-0-4"]["registration"] == "verified"
    assert observations["worker-0-4"]["value"] == 0
    assert "相同工具和参数已经尝试" not in observations["worker-0-4"].get("error", "")
    assert registry.get("generated_tools","custom_x")["source"] == fixed


def test_sample_only_registration_is_not_cited_as_evidence(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='仅样例校验', limitations='未经真实调用验证', next_step='用真实输入验证', action='validate')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                if context["observations"]:
                    return schema(action="finish", objective_or_conclusion="custom tool works",
                                  evidence=["worker-0-0"])
                return schema(action="delegate", objective_or_conclusion="register a numeric function")
            if "0-1-" in id:
                return schema(action="return", hypothesis_or_finding="registered but unverified",
                              prediction_or_limitation="no real input tested")
            return schema(action="experiment", tool="register_tool",
                          arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                     "source":"x=>x.n*2"},
                          hypothesis_or_finding="register", prediction_or_limitation="sample passes")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=2,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    assert result["status"] == "inconclusive"
    assert "worker-0-0" not in result["citations"]
    assert "custom_double" in result["summary"]


def test_register_tool_rejects_host_apis_and_is_never_blocked(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='环境不支持 require', limitations='需纯函数', next_step='改用纯 JS 重写', action='revise')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="register and verify")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":"x => require('os') || x.n*2"},
                              hypothesis_or_finding="register", prediction_or_limitation="node style")
            if "0-1-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":"x=>x.n*2"},
                              hypothesis_or_finding="register v2", prediction_or_limitation="pure function")
            if "0-2-" in id:
                return schema(action="experiment", tool="custom_double", arguments={"inputs":{"n":11}},
                              hypothesis_or_finding="verify", prediction_or_limitation="real input")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="verified")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=4,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert "宿主 API" in observations["worker-0-0"]["error"]
    assert observations["worker-0-1"]["registered"] == "custom_double"
    assert observations["worker-0-2"]["registration"] == "verified"
    assert registry.get("generated_tools","custom_double")["source"] == "x=>x.n*2"


def test_reregistering_a_verified_tool_is_rejected(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled":True,"base_url":"http://test","model":"fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'EvidenceReview':
                return schema(summary='核对', limitations='样例有限', next_step='换输入', action='validate')
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="numeric function",tools=[])
            if schema.__name__ == "Direction":
                return schema(action="delegate", objective_or_conclusion="verify custom tool")
            if "0-0-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"double n","example":{"n":2},"expected":4,
                                         "source":"x=>x.n*2"},
                              hypothesis_or_finding="register", prediction_or_limitation="sample passes")
            if "0-1-" in id:
                return schema(action="experiment", tool="custom_double", arguments={"inputs":{"n":11}},
                              hypothesis_or_finding="verify", prediction_or_limitation="real input")
            if "0-2-" in id:
                return schema(action="experiment", tool="register_tool",
                              arguments={"name":"custom_double","purpose":"triple n","example":{"n":2},"expected":6,
                                         "source":"x=>x.n*3"},
                              hypothesis_or_finding="re-register", prediction_or_limitation="different implementation")
            return schema(action="return", hypothesis_or_finding="done", prediction_or_limitation="recorded")
    registry = Registry(tmp_path)
    task = Task(goal="Double n",domain="math",max_worker_turns=4,max_delegations=1)
    result = research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
    observations = result["evidence"]
    assert "已正式注册" in observations["worker-0-2"]["error"]
    assert registry.get("generated_tools","custom_double")["source"] == "x=>x.n*2"

