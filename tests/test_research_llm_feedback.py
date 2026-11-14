import json

import httpx

from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.gateway import ScienceGateway
from lazyresearch.science.registry import Registry


def test_model_reviews_counterexample_and_worker_uses_feedback(tmp_path, monkeypatch):
    calls = []
    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body['messages'][1]['content'])
        rid = request.headers['X-Client-Request-Id']
        calls.append((rid, context))
        if rid.startswith('review-'):
            assert context['observation']['verdict'] in {'refuted', 'supported'}
            answer = dict(summary='线性假设存在反例', limitations='仅覆盖已给数列',
                          next_step='改为二次多项式', action='revise')
        elif rid.startswith('director-'):
            answer = dict(action='delegate', objective_or_conclusion='验证多项式')
        else:
            if context['history']:
                assert context['history'][-1]['review']['next_step'] == '改为二次多项式'
            answer = dict(action='experiment', tool='sequence',
                          arguments={'coefficients': [1, 0, 1] if context['history'] else [1, 1]},
                          hypothesis_or_finding='多项式拟合', prediction_or_limitation='全部观测应匹配')
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}],
                                        'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})
    task = Task(goal='解释数列', sequence=[1, 2, 5, 10], max_delegations=1,
                budget={'max_experiments': 2})
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, task.budget)
    cfg = ModelConfig(local={'enabled': True, 'base_url': 'http://fixture', 'model': 'test'})
    gateway = ScienceGateway(cfg, registry, budget, httpx.MockTransport(respond), allow_reporting=True)
    report = research(task, task.model_dump(), registry, gateway, budget)
    assert report['evidence']['worker-0-0']['verdict'] == 'refuted'
    assert report['evidence']['worker-0-1']['verdict'] == 'supported'
    assert len(registry.list('research_reviews')) == 2
    assert any(rid == 'review-worker-0-0-local' for rid, _ in calls)


def test_planning_keeps_discovery_and_generation_available(tmp_path):
    class Gateway:
        config = ModelConfig(local={'enabled': True, 'base_url': 'http://fixture', 'model': 'test'})
        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == 'CapabilityPlan':
                return schema(objective='先读取环境数据', tools=['read_material'])
            if schema.__name__ == 'Direction':
                assert 'register_tool' in context['tools']
                assert 'inspect_csv' in context['tools']
                return schema(action='delegate', objective_or_conclusion='检查字段后设计实验')
            return schema(action='return', hypothesis_or_finding='缺少实测数据', prediction_or_limitation='不能编造')
    task = Task(goal='新领域任务', domain='生态研究', max_delegations=1)
    registry = Registry(tmp_path)
    research(task, {**task.model_dump(), 'csv_files': True}, registry, Gateway(),
             BudgetGovernor(registry, task.budget))
