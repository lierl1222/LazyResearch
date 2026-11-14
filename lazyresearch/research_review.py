"""Model interpretation kept separate from executable verification and measured scores."""
from typing import Literal

from pydantic import Field

from .models import Record
from .model_context import compact_text
from .science.budget import BudgetExceeded


class EvidenceReview(Record):
    summary: str = Field(min_length=1, max_length=600)
    limitations: str = Field(min_length=1, max_length=400)
    next_step: str = Field(min_length=1, max_length=600)
    action: Literal['revise', 'validate', 'continue', 'insufficient_data']


def review_evidence(ask, registry, emit, id, goal, hypothesis, outcome, *, prior=(), round=1):
    """A separate reviewer sees actual results; its opinion never overwrites evidence."""
    # Do not seed the independent reviewer with earlier reviewers' conclusions.
    previous = [{k: v for k, v in item.items() if k != 'review'} for item in list(prior)[-4:]]
    context = compact_text(dict(goal=goal, hypothesis=hypothesis, observation_id=id,
                                observation=outcome, previous_results=previous), 1800)
    try:
        decision = ask('review-' + id,
            '你是独立研究评审。根据真实工具结果检查假设是否有证据支持、字段是否匹配、验证是否独立、'
            '有没有泄漏或重复实验。observed 仅表示执行过，工具注册样例通过不等于研究假设得到验证。'
            '先从研究领域的定义独立推导应计算的量、单位和正负号，再核对工具源码，'
            '不能因为样例与代码一致就认可公式，也不能仅修改 expected 迎合错误代码。'
            'RMSLE 越小越好，只有相同开发折可比较；最终留出集结果不得用于后续调参。'
            '指出具体限制，给出下一步可执行的参数调整、字段检查、工具补充或反例检验。'
            '缺少真实数据则返回 insufficient_data，禁止建议编造输入。不得修改实测分数或宣称未进行的验证。',
            context, EvidenceReview, complex_step=bool(outcome.get('error') or
                hypothesis.get('tool', '').startswith('custom_') or hypothesis.get('tool') == 'register_tool')
                if isinstance(hypothesis, dict) else bool(outcome.get('error')))
        record = dict(id=id, status='completed', **decision.model_dump())
    except (RuntimeError, BudgetExceeded) as error:
        record = dict(id=id, status='unavailable', reason=str(error))
    registry.put('research_reviews', record, id)
    if record['status'] == 'completed':
        emit('revision', round=round, observation_id=id,
             summary=f"独立模型评审：{record['summary']} 限制：{record['limitations']} 下一步：{record['next_step']}")
    else:
        emit('revision', round=round, observation_id=id, summary='模型评审未完成，保留工具实测结果：' + record['reason'])
    return record
