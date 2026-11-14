from lazyresearch.configuration import ModelConfig
from lazyresearch.final_report import finalize_result, report_context
from lazyresearch.research import Task
from lazyresearch.results import result_markdown
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.registry import Registry


def make_report():
    return {"status": "reported", "summary": "已完成。", "citations": ["worker-0-0"],
            "evidence": {"worker-0-0": {"verdict": "observed", "value": 22}},
            "delegations": [], "budget": {}}


def setup(tmp_path):
    registry = Registry(tmp_path)
    task = Task(goal="研究目标")
    registry.put("task", task.model_dump())
    return registry, task, BudgetGovernor(registry, task.budget)


def test_final_report_uses_cloud_markdown(tmp_path):
    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, role, id, instruction, context, *, output_tokens=None):
            assert role == "cloud"
            assert context["evidence"] and context["goal"] == "研究目标"
            assert output_tokens and output_tokens >= 400
            return "## 摘要\n\n" + "锁定方案的实测结果如上，方法见实验记录。" * 10, False

    registry, task, budget = setup(tmp_path)
    report = make_report()
    result = finalize_result(registry, report, Gateway(), budget)
    assert result.startswith("# 研究报告") and "研究目标" in result and "## 摘要" in result
    assert registry.get("final_report")["source"] == "cloud"
    assert not registry.get("final_report")["truncated"]
    assert (tmp_path / "result.md").read_text(encoding="utf8") == result
    assert result_markdown(registry, report) == result


def test_final_report_accepts_truncated_output_with_note(tmp_path):
    body = "## 摘要\n\n" + "实测证据表明候选有效。" * 40

    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, role, id, instruction, context, *, output_tokens=None):
            return body, True

    registry, task, budget = setup(tmp_path)
    result = finalize_result(registry, make_report(), Gateway(), budget)
    assert "报告内容可能不完整" in result
    assert registry.get("final_report")["source"] == "cloud"
    assert registry.get("final_report")["truncated"]


def test_final_report_falls_back_when_output_too_short(tmp_path):
    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, role, id, instruction, context, *, output_tokens=None):
            return "太短", True

    registry, task, budget = setup(tmp_path)
    result = finalize_result(registry, make_report(), Gateway(), budget)
    assert "## 实验记录" in result
    assert registry.get("final_report")["source"] == "template"
    assert not registry.get("final_report").get("markdown")


def test_final_report_falls_back_without_cloud(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask_text(self, *args, **kwargs):
            raise AssertionError("must not be called")

    registry, task, budget = setup(tmp_path)
    result = finalize_result(registry, make_report(), Gateway(), budget)
    assert "## 实验记录" in result
    assert registry.get("final_report") is None
    assert (tmp_path / "result.md").exists()


def test_final_report_falls_back_when_cloud_call_fails(tmp_path):
    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, *args, **kwargs):
            raise RuntimeError("ConnectError")

    registry, task, budget = setup(tmp_path)
    result = finalize_result(registry, make_report(), Gateway(), budget)
    assert "## 实验记录" in result
    assert registry.get("final_report")["source"] == "template"
    assert "ConnectError" in registry.get("final_report")["reason"]


def test_final_report_skips_without_evidence(tmp_path):
    calls = []

    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, *args, **kwargs):
            calls.append(args)
            return "## 摘要\n\n不应被调用。", False

    registry, task, budget = setup(tmp_path)
    report = {"status": "failed", "summary": "boom", "citations": [], "evidence": {},
              "delegations": [], "budget": {}}
    result = finalize_result(registry, report, Gateway(), budget)
    assert not calls
    assert "状态：执行失败" in result
    assert registry.get("final_report") is None


def test_final_report_skips_when_only_errors(tmp_path):
    calls = []

    class Gateway:
        config = ModelConfig(cloud={"enabled": True, "base_url": "https://cloud.example", "model": "big"})

        def ask_text(self, *args, **kwargs):
            calls.append(args)
            return "## 摘要\n\n不应被调用。", False

    registry, task, budget = setup(tmp_path)
    report = {"status": "inconclusive", "summary": "全部失败", "citations": [],
              "evidence": {"worker-0-0": {"error": "boom"}}, "delegations": [], "budget": {}}
    result = finalize_result(registry, report, Gateway(), budget)
    assert not calls
    assert "状态：证据不足" in result
    assert registry.get("final_report") is None


def test_report_context_compacts_pending_tools(tmp_path):
    registry, task, budget = setup(tmp_path)
    registry.put("pending_tools", {"name": "custom_big", "status": "unverified", "failures": 1,
                                   "version": 1, "purpose": "p" * 300,
                                   "source": "s" * 12000, "last_error": "e" * 300}, "custom_big")
    report = make_report()
    context = report_context(registry, report, budget)
    entry = context["pending_tools"][0]
    assert entry["name"] == "custom_big" and entry["status"] == "unverified"
    assert len(entry["source"]) < 500
    assert len(context["project_documents"]) == 0
