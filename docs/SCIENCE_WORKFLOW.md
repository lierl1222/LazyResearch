# 角色化表格研究工作流

```mermaid
flowchart TD
    A["initialize<br/><b>DataScientist</b> · 确定性<br/>校验、安全划分、训练集 EDA"] --> B["baseline<br/><b>AlgorithmEngineer</b> · 确定性<br/>Dummy + Logistic 基线"]
    B --> C["hypothesize<br/><b>HypothesisScientist</b> · 确定性<br/>生成 4 张可证伪假设卡片<br/>⇩<br/><b>ResearchDirector</b> · 云端模型决策<br/>选牌排序 ResearchPlan<br/>hypothesis_ids 硬校验：必须精确匹配卡片"]
    C -->|"采纳"| D["plan_experiment<br/><b>AlgorithmEngineer</b> · 确定性<br/>模板 → 白名单 ExperimentSpec"]
    C -->|"规划失败 / 预算耗尽"| H
    D --> E["execute<br/><b>BudgetGovernor</b> · 硬拦截<br/>持久化预留 → 独立进程 → 用量对账<br/><b>ScientificReviewer</b> · 统计<br/>配对 Bootstrap + 调整区间"]
    E --> F["review<br/><b>ScientificReviewer</b> · 统计结论<br/>accept / reject / inconclusive / invalid"]
    F --> G["decide<br/><b>ResearchDirector</b> · 确定性规则<br/>耐心值、模板顺序、预算保留、目标分<br/>⇩<br/><b>本地模型</b> · 决策 Selection<br/>选下一假设；停滞 ≥2 轮升级云端<br/>失败 → deterministic_fallback"]
    G -->|"continue"| D
    G -->|"stop / 假设耗尽 / 预算耗尽"| H
    H["final_evaluate<br/>确定性<br/>冻结验证集最优 → 测试门一次性消费 → 封存测试"] --> I["export<br/>确定性<br/>report.md · manifest · JSONL · 模型"]
    I --> END["END"]
```

任一节点返回 `stop_reason` 都经条件边进入 final_evaluate（交付已有成果），图中仅标注主要失败路径。LangGraph 管理循环与 checkpoint，SQLite Registry 是研究记录及预算的权威来源，JSONL 是审计导出。角色是职责划分，不是每步固定调用模型；BudgetGovernor 和科学计算完全是确定性代码。Mock 模式以受控策略替代模型决策，实验仍真实执行。

研究实验顺序执行，使后续决策能引用最新证据，并避免 CPU 和 Token 预留竞争。原 fixture 主图的独立候选并行仍保留；科学研究没有为追求“多 Agent”数量而引入没有证据收益的并行调用。

恢复时沿用已完成实验；已开始但结果不明的操作不自动重复。最终测试消费标记先于测试读取；报告导出不触发训练或额外收费调用。
