import json

import httpx
import pytest
from fastapi import HTTPException

from lazyresearch.configuration import ModelConfig
from lazyresearch.research_service import ResearchService, Submission
from lazyresearch.session import Question, ask
from lazyresearch.science.gateway import ScienceGateway


def test_followup_run_reuses_material_and_local_conversation(tmp_path):
    config = ModelConfig()
    config.local.enabled = True
    config.local.base_url = "http://example.test"
    config.local.model = "test"
    prompts = []

    def respond(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        prompts.append(context)
        decision = ({"answer": "我记得校准条件。"} if "question" in context else
                    {"action": "finish", "objective_or_conclusion": "需要更多证据"})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

    service = ResearchService(tmp_path, config, lambda c, r, b, **kw:
        ScienceGateway(c, r, b, httpx.MockTransport(respond), **kw))
    submission = Submission(goal="测试原假设", sequence=[1, 2, 5], budget={"max_cloud_requests": 0})
    assert submission.budget.max_llm_calls is None
    first = service.create(submission)
    with pytest.raises(HTTPException, match="正在"):
        service.create(Submission(goal="继续", previous_run_id=first))
    previous = service.registry(first)
    previous.put("report", {"status": "stopped", "summary": "已找到反例",
                            "evidence": {"worker-0-0": {"verdict": "refuted", "n": 2}}})
    (previous.root / "stop.requested").touch()
    ask(service, first, Question(message="记住校准条件", local_only=True))
    second = service.create(Submission(goal="继续", previous_run_id=first))
    service.run(second)
    assert service.registry(second).get("task")["sequence"] == [1, 2, 5]
    assert service.snapshot(second)["conversation_id"] == first
    assert [row["id"] for row in service.snapshot(second)["research_history"]] == [first]
    assert "已找到反例" in str(prompts[-1]["previous_research"])
    assert "校准条件" in str(prompts[-1]["research_dialogue"])
    ask(service, second, Question(message="什么条件？", local_only=True))
    assert "记住校准条件" in str(prompts[-1]["recent_dialogue"])
    independent = service.create(Submission(goal="独立任务", domain="统计"))
    assert service.snapshot(independent)["exchanges"] == []


def test_inspection_progress_omits_internal_fields():
    from lazyresearch.presentation import present_events

    event = {"id": 1, "round": 2, "stage": "validation", "observation_id": "worker-1-0",
             "outcome": {"verdict": "observed", "match": False, "length": 121800373,
                         "wall_seconds": 1.66, "config_hash": "private metadata"}}
    display = present_events([event])[0]["display"]
    assert "第 2 轮" in display["title"]
    assert "未找到匹配内容" in display["summary"]
    assert "config_hash" not in str(display)
    assert "worker-1-0" not in str(display)
    assert "121,800,373" in str(display)


def test_tool_registry_reloads_and_rejects_imports_outside_tools(tmp_path):
    from lazyresearch.research_tools import execute_tool, load_tools

    config = tmp_path / "tools.toml"
    config.write_text(
        '[tools.check]\nmaterial="sequence"\nlabel="验证数列"\npurpose="验证给定数列"\n'
        'module="sequence"\nschema="Polynomial"\nfunction="sequence"\n', encoding="utf8")
    loaded = load_tools(config)
    assert list(loaded) == ["check"]
    outcome = execute_tool(tmp_path, {"tool_spec": loaded["check"].model_dump(by_alias=True),
                                     "task": {"sequence": [1, 3]}, "arguments": {"coefficients": [1, 2]}})
    assert outcome["verdict"] == "supported"
    config.write_text('[tools]\n', encoding="utf8")
    assert not load_tools(config)
    config.write_text(
        '[tools.check]\nmaterial="sequence"\nlabel="验证数列"\npurpose="验证给定数列"\n'
        'module="..research"\nschema="Task"\nfunction="research"\n', encoding="utf8")
    with pytest.raises(ValueError, match="check"):
        load_tools(config)
