"""Explicit live-model checks. Run from repo root; artifacts and requests remain auditable."""
import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lazyresearch.configuration import load_model_config
from lazyresearch.research import Task, research, append_report
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.gateway import ScienceGateway
from lazyresearch.science.registry import Registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=['sequence', 'custom', 'forecast'])
    parser.add_argument('--prior-run', type=Path)
    parser.add_argument('--cloud-first', action='store_true')
    args = parser.parse_args()
    root = Path('runs') / ('llm-check-' + args.case + '-' + uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    cfg = load_model_config()
    if args.cloud_first:
        cfg.local.enabled = False
    cfg.cloud.max_output_tokens = max(cfg.cloud.max_output_tokens, 1200)
    task = Task(goal='寻找匹配数列的整数多项式，检验至少一个竞争假设的反例，并说明有限观测范围。',
                sequence=[1, 2, 5, 10, 17, 26], max_delegations=2, max_worker_turns=4,
                budget={'max_experiments': 5, 'max_cloud_requests': 10,
                        'max_wall_time_seconds': 360, 'max_llm_output_tokens': 24000})
    material = task.model_dump()
    if args.case == 'custom':
        task.domain = '水文分析'
        task.sequence = []
        task.goal = ('研究流域水量平衡。实测降水120 mm、蒸散45 mm、径流55 mm、储量增加20 mm。'
                     '检查余额是否为零，再用径流65 mm作为反例。现有工具不足时编写可复用纯函数，'
                     '注册样例通过后必须调用该工具处理上述真实观测。不要把示例当研究结果。')
        material = task.model_dump()
    if args.case == 'forecast':
        if not args.prior_run:
            parser.error('forecast requires --prior-run with the existing Favorita inputs')
        prior = Registry(args.prior_run).get('task')
        task.goal = '在同一开发折最小化 Favorita RMSLE。根据每次实测和独立评审调整参数，完成三个不同候选后锁定最优方案验证。'
        task.sequence = []
        task.max_delegations = 3
        task.budget.max_experiments = 4
        task.budget.max_wall_time_seconds = 600
        material = {**prior, **task.model_dump(), 'favorita_files': True, 'csv_files': True}
        (root / 'inputs').mkdir()
        for file in prior['files']:
            shutil.copyfile(args.prior_run / 'inputs' / file['id'], root / 'inputs' / file['id'])
    registry = Registry(root)
    registry.put('task', material)
    budget = BudgetGovernor(registry, task.budget)
    def emit(stage, **details):
        append_report(root, stage, details)
        if stage in {'model_request', 'validation', 'conclusion'}:
            print(stage, details.get('request_id', details.get('observation_id', details.get('summary', ''))), flush=True)
    output = research(task, material, registry, ScienceGateway(cfg, registry, budget, allow_reporting=True), budget, emit)
    registry.put('report', output)
    (root / 'report.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    calls = registry.list('model_calls')
    reviews = registry.list('research_reviews')
    summary = {'case': args.case, 'run': str(root), 'status': output['status'],
               'summary': output['summary'], 'experiments': output['budget']['experiment_count'],
               'successful_model_calls': sum(c['status'] == 'completed' for c in calls),
               'failed_model_calls': sum(c['status'] != 'completed' for c in calls),
               'completed_reviews': sum(r['status'] == 'completed' for r in reviews),
               'observations': {k: {n: v[n] for n in ('verdict', 'candidate', 'value', 'error') if n in v}
                                for k, v in output['evidence'].items()}}
    (root / 'check.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
