import httpx

from lazyresearch.configuration import ModelConfig
from lazyresearch.science.agents import HypothesisScientist
from lazyresearch.science.graph import ScienceRunner
from lazyresearch.science.schemas import TaskConfig


def cloud_runner(tmp_path, responses):
    task = TaskConfig.model_validate({"dataset": {"path": "unused.csv", "target": "y"},
                                     "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test"}})

    def handle(request):
        rid = request.headers.get("X-Client-Request-Id", "")
        return httpx.Response(200, json={"choices": [{"message": {"content": responses[rid]}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
    runner = ScienceRunner(tmp_path, task, config)
    runner.gateway.transport = httpx.MockTransport(handle)
    return runner


def test_custom_tool_registered_verified_and_executed(tmp_path):
    responses = {
        "hypotheses-cloud": ('{"summary":"custom check","registrations":[{"definition":{"name":"custom_sum",'
                             '"purpose":"sum of a and b","source":"x => ({s: x.a + x.b})",'
                             '"example":{"a":1,"b":2},"expected":{"s":3}},"justification":"verify additive identity"}],'
                             '"hypotheses":[{"id":"h-custom","claim":"The tool reports the configured sum.",'
                             '"predicted_effect":"value.s equals a plus b","falsification_condition":"value.s differs from a plus b",'
                             '"experiment_type":"custom_sum","priority":1}]}'),
        "engineer-0-cloud": '{"features":[],"model_name":"logistic","model_params":{},"inputs":{"a":10,"b":32}}',
    }
    runner = cloud_runner(tmp_path, responses)
    runner.registry.put("profile", {"id": "dataset-profile", "features": ["a", "b"]})
    assert runner.hypothesize({})["next_template"] == "custom_sum"
    assert runner.registry.list("science_tools")[0]["name"] == "custom_sum"
    plan = runner.plan_experiment({"iteration": 0, "next_template": "custom_sum"})
    assert plan["current_experiment"] == "experiment-1"
    spec = runner.registry.get("plans", "experiment-1")
    assert spec["experiment_type"] == "custom_tool" and spec["tool_name"] == "custom_sum"
    runner.execute({"iteration": 0, "completed_templates": [], "current_experiment": "experiment-1"})
    result = runner.registry.get("experiments", "experiment-1")
    assert result["value"] == {"s": 42}
    assert result["review"]["verdict"] == "observed"
    resumed = ScienceRunner(tmp_path, runner.config, runner.gateway.config)
    assert resumed.tools['custom_sum']['source'] == 'x => ({s: x.a + x.b})'


def test_broken_example_tool_is_not_registered(tmp_path):
    responses = {
        "hypotheses-cloud": ('{"summary":"broken tool","registrations":[{"definition":{"name":"custom_bad",'
                             '"purpose":"bad","source":"x => ({s: x.a + 1})",'
                             '"example":{"a":1},"expected":{"s":99}},"justification":"must fail"}],'
                             '"hypotheses":[{"id":"h-good","claim":"Built-in still works.","predicted_effect":"AP improves.",'
                             '"falsification_condition":"AP interval includes zero.","experiment_type":"nonlinear_model","priority":1}]}'),
    }
    runner = cloud_runner(tmp_path, responses)
    runner.registry.put("profile", {"id": "dataset-profile", "features": ["a", "b"]})
    assert runner.hypothesize({})["next_template"] == "nonlinear_model"
    assert not runner.registry.list("science_tools")
    assert runner.registry.get("hypotheses", "h-good")


def test_review_records_model_analysis(tmp_path):
    task = TaskConfig.model_validate({"dataset": {"path": "unused", "target": "y"},
                                     "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"local": {"enabled": True, "base_url": "http://local.invalid", "model": "small"}})
    runner = ScienceRunner(tmp_path, task, config)
    runner.registry.put("experiments", {"experiment_id": "e1", "hypothesis_id": "h1",
                                        "spec": {"experiment_type": "feature_interaction"},
                                        "metrics": {"average_precision": .8},
                                        "review": {"id": "review-e1", "experiment_id": "e1", "hypothesis_id": "h1",
                                                   "verdict": "reject", "reason": "interval includes zero"}}, "e1")
    runner.registry.put("hypotheses", {"id": "h1", "experiment_type": "feature_interaction", "status": "proposed"}, "h1")
    payload = {"choices": [{"message": {"content": '{"summary":"Weak support.","implications":"AP gain not established.",'
                                                  '"anomalies":"","suggested_next":"Try tree model."}'}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 10}}
    runner.gateway.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    update = runner.review({"iteration": 1, "stalled": 0, "current_experiment": "e1", "current_hypothesis": "h1"})
    assert update["stalled"] == 1
    analysis = runner.registry.get("analyses", "analysis-e1")
    assert analysis["summary"] == "Weak support."
    assert runner.registry.get("model_calls", "analysis-1-local")["role"] == "local"


def test_model_failure_falls_back_to_deterministic_roles(tmp_path):
    task = TaskConfig.model_validate({"dataset": {"path": "unused", "target": "y"},
                                     "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test"}})
    runner = ScienceRunner(tmp_path, task, config)
    runner.registry.put("profile", {"id": "dataset-profile", "features": ["a", "b"]})
    runner.gateway.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    assert runner.hypothesize({})["next_template"] == "feature_interaction"
    assert len(runner.registry.list("hypotheses")) == 4
    assert runner.registry.get("fallback")["mode"] == "deterministic_fallback"


def test_director_proposes_new_hypotheses_when_exhausted(tmp_path):
    responses = {
        "director-1-cloud": '{"action":"stop","next_experiment_type":"","reason":"All cards exhausted.","evidence_ids":[]}',
        "new-hypotheses-1-cloud": ('{"summary":"Revised nonlinear idea","registrations":[],'
                                   '"hypotheses":[{"id":"h-revised","claim":"Regularized trees capture nonlinearity.",'
                                   '"predicted_effect":"AP improves.","falsification_condition":"AP interval includes zero.",'
                                   '"experiment_type":"nonlinear_model","priority":1}]}'),
    }
    runner = cloud_runner(tmp_path, responses)
    runner.registry.put("profile", {"id": "dataset-profile", "features": ["a", "b"]})
    for h in HypothesisScientist().propose({"id": "p", "features": ["a", "b"]}):
        runner.registry.put("hypotheses", h.model_dump(), h.id)
    runner.registry.put("reviews", {"id": "review-e1", "verdict": "reject"}, "review-e1")
    runner.registry.put("experiments", {"experiment_id": "e1", "metrics": {}}, "e1")
    completed = [h["experiment_type"] for h in runner.registry.list("hypotheses")]
    update = runner.decide({"iteration": 1, "stalled": 0, "completed_templates": completed,
                            "current_experiment": "e1"})
    assert update["next_template"] == "nonlinear_model"
    assert "review-e1" in runner.registry.get("hypotheses", "h-revised")["observations"]
    assert runner.registry.get("decisions", "decision-1")["action"] == "continue"
    old = next(h for h in runner.registry.list('hypotheses')
               if h['experiment_type'] == 'nonlinear_model' and h['id'] != 'h-revised')
    runner.registry.put('experiments', {'hypothesis_id': old['id']}, 'old-tree-experiment')
    responses['engineer-1-cloud'] = '{"features":[],"model_name":"random_forest","model_params":{},"inputs":{}}'
    plan = runner.plan_experiment({'iteration': 1, 'next_template': 'nonlinear_model'})
    assert plan['current_hypothesis'] == 'h-revised'


def test_routing_escalates_to_cloud_when_stalled(tmp_path):
    task = TaskConfig.model_validate({"dataset": {"path": "unused", "target": "y"},
                                     "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"local": {"enabled": True, "base_url": "http://local.invalid", "model": "small"},
                                         "cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test"}})
    runner = ScienceRunner(tmp_path, task, config)
    for h in HypothesisScientist().propose({"id": "p", "features": ["a", "b"]}):
        runner.registry.put("hypotheses", h.model_dump(), h.id)
    runner.registry.put("reviews", {"id": "review-e1", "verdict": "reject"}, "review-e1")
    runner.registry.put("experiments", {"experiment_id": "e1", "metrics": {}}, "e1")
    routing = '{"action":"continue","next_experiment_type":"nonlinear_model","reason":"Try trees.","evidence_ids":["review-e1"]}'

    def handle(request):
        assert request.headers.get("X-Client-Request-Id") == "director-2-cloud"
        return httpx.Response(200, json={"choices": [{"message": {"content": routing}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 5}})
    runner.gateway.transport = httpx.MockTransport(handle)
    update = runner.decide({"iteration": 2, "stalled": 2, "completed_templates": [], "current_experiment": "e1"})
    assert update["next_template"] == "nonlinear_model"
    assert runner.registry.get("decisions", "decision-2")["source"] == "cloud"
