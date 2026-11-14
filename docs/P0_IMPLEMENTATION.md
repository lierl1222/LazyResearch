# G0 / P0 融合实施与验收

依据：`RESEARCH_AGENT_GOALS.md`。本轮范围为 G0、G2–G9 和 Phase 1–3；G1 的客户响应作为默认业务说明，通用二分类输入仍可使用。P1 控制台迁移、Optuna/Single-Agent 对照及 P2 记忆不属于本轮完成声明。

## 融合方案

保留 LazyResearch 名称、现有 Web/API、模型配置与 fixture 回归入口。在 `lazyresearch/science/` 增加表格研究引擎，复用 LangGraph 与 SQLite 检查点。现有 fixture 的 `accepted` 布尔值不可充当真实实验指标。

独立职责：ResearchDirector 负责决策与停止；DataScientist 负责安全数据划分及 EDA；HypothesisScientist 负责证据驱动假设；AlgorithmEngineer 负责白名单实验配置；ScientificReviewer 负责同协议比较及不确定性；BudgetGovernor 是硬拦截代码。模型仅返回受校验的研究决策，不执行生成代码。

考虑过直接扩展 FixtureAdapter 和重建 Streamlit 应用。前者现有数据契约不足以表达封存测试及多维预算，后者会将 P1 带入 P0。因此新增独立科学模块，共用现有应用的配置入口，并保留原闭环兼容性。

## 实施任务与证据

- [x] Phase 1：`schemas.py`、`data.py`、`experiments.py`；配置解析、CSV/Parquet、合成数据、分层/时间切分、训练集拟合预处理、Dummy/LR 真指标。测试非法标签、禁用字段、划分互斥、缺失类别、真实基线。
- [x] Phase 2：`agents.py`、`graph.py`；结构化假设、四个受控模板、反馈分支、Mock/真实双模型路由。测试两种非等价假设、至少三次实验、反馈改变下一步、非法模型参数拒绝。
- [x] Phase 3：`budget.py`、`registry.py`、`reporting.py`；持久化预留与用量对账、子进程超时终止、CPU/墙钟计量、Bootstrap 审查、最终锁定及一次测试、恢复与导出。测试极低预算、失败/超时、未知用量保留、重启不重复执行或打开测试集。
- [x] 交付：CLI run/resume/reproduce、示例配置、部署脚本、README、PROGRESS；离线 demo 和复现结果验证，保留全部原有测试。

验收证据与真实联调限制见 [P0_ACCEPTANCE_REPORT.md](P0_ACCEPTANCE_REPORT.md)。

## 硬约束

固定种子与划分索引、数据和配置哈希；测试集在冻结前不参与 EDA/研究决策；最终评估也受预算约束，额度不足则明确未执行。所有实验含 run_id、experiment_id、hypothesis_id、配置哈希、耗时、指标及决策引用。失败和无改善是合法结果。真实调用用量缺失时标记未知并保留预留，不虚构价格。Mock 模式在报告与 manifest 明示。

## 验收重点

数据单类/稀有类、全空列、时间切分单类、目标衍生字段；预算在调用失败和进程终止后仍一致；最终评估崩溃后的恢复不得重复消费测试；产物报告数值逐项对应日志；相同输入和配置复现可比较指标，环境差异明确记录。

不存在可以先验保证的“理论最优”编排；以可靠性、实际成本、可复现与证据驱动的决策作为本轮可验证标准。
