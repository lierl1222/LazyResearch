# SignalMine — 自主数据挖掘与算法研究 Agent

> **执行型项目任务书 / Agent Build Spec**  
> 文档用途：直接交给 Codex、Claude Code 或其他编码 Agent，作为项目实施、测试和验收依据。  
> 项目形态：Python 本地研究引擎 + 轻量 Web 研究控制台。  
> 当前阶段：比赛 MVP，优先交付可运行、可验证的研究闭环；不追求生产级分布式系统。

---

## 0. Agent 的最高优先级指令

你是一名负责完整交付本项目的工程 Agent。你的任务不是产出架构讨论、静态页面或伪造的研究报告，而是**构建、运行、测试一个能自主完成数据科学研究闭环的系统**。

执行规则：

1. **先交付端到端最小闭环，再增加功能。** 任何新模块必须能通过真实调用产生可检查的结果。
2. **不要假设实验有正向提升。** 即使所有候选方案失败，系统也应报告真实结果和失败原因，并完成可追溯交付。
3. **确定性计算交给 Python，研究决策交给 LLM。** 禁止用模型编造统计指标、训练结果、实验耗时和调用成本。
4. **每轮研究必须有可检验假设。** 假设须含预测、实验方法、证伪条件和结果解释；禁止仅用随机搜索冒充自主研究。
5. **严禁测试集泄漏。** 最终测试集只在研究方案锁定后做一次最终评估；所有研究迭代仅能使用训练集和验证集/交叉验证结果。
6. **预算必须硬约束。** Token、调用次数、实验次数、CPU 执行时间都必须可限制、可记录、可停止。
7. **调用失败必须安全降级。** 模型 API 不可用时，仍应可使用 Mock LLM 和受控策略完成 CI 测试及本地 Demo；不得把 Mock 结果当作真实 LLM 研究成果。
8. **不要向用户反复追问已明确的技术决策。** 缺少非关键输入时按本文默认方案实施，并记录假设。
9. **每个开发阶段结束都运行测试并更新进度文件。** 完成后提交运行命令、测试结果、已知局限。
10. 生成或执行代码应遵守沙箱限制：只允许预定义科学工具和受控实验配置，不直接执行 LLM 生成的任意 shell/Python 代码。

---

## 1. 明确的 Product Goal

### G0 — 总目标（必须实现）

**构建一个面向结构化表格数据的自主研究 Agent：用户输入 CSV/Parquet 数据、目标字段、业务目标及资源预算，系统自动完成：目标规划 → 数据探索 → 提出假设 → 设计实验 → 执行算法 → 统计验证 → 反证与修正 → 交付可复现成果。**

系统核心产出不是一个模型文件，而是：

- **业务结果**：经过验证的分类模型、指标，以及可选的高价值子群体/规则发现；
- **科研过程**：机器可读的研究假设、证据、实验、失败理由、决策轨迹；
- **资源透明度**：模型调用 Token、实际或估算 API 费用、运行时间、实验次数；
- **可复现性**：固定随机种子、数据划分、版本化配置、实验日志与复现命令。

### G0 验收标准

给定一份合法的二分类表格数据和任务配置：

1. 单条 CLI 命令可启动自主研究，直至预算耗尽、目标达到或达到停止条件。
2. 至少建立一个基线模型，并产生至少 **2 个彼此有实质区别的可检验研究假设**；当预算允许时，至少执行 **3 个真实算法/特征实验**。
3. 每个实验有完整的 `hypothesis_id → experiment_id → metrics → decision` 关联。
4. 至少实现一次根据**真实实验结果**进行的后续决策：保留、否定、修正假设、重新实验或停止。
5. 按固定协议产生对比报告，报告中所有数值均能回溯到原始记录。
6. 接入真实 LLM 时统计实际输入、输出 Token；无法获得用量时明确标注“估算/未知”，不编造计费数据。
7. 预算达到上限后不再发起收费 LLM 调用或新的计算实验，仍能导出已有成果。
8. 使用同一数据、划分、种子和配置可以复现训练与评估流程；允许记录合理的环境或数值差异。
9. Web 页面能查看任务状态、假设演化、实验对比、预算消耗和最终结论（若页面未就绪，CLI 与 JSON/Markdown 报告必须先完整可用）。

**重要：不把“必须打败所有基线”列为正确性验收条件。** Agent 有可能得出“当前预算下未发现稳定提升”，这属于有效研究结果。竞赛成绩再单独对照改善幅度。

---

## 2. 收束的业务场景（MVP 固定）

### G1 — 客户响应预测与高价值人群挖掘

**业务问题：** 企业只有固定比例的客户触达预算，如何从历史客户与交互记录中构建可靠的响应预测模型，寻找具有较高响应倾向的客户群体，并验证相关规律在独立数据上是否稳定？

- **用户**：企业数据分析师、算法研究员、业务增长研究团队。
- **输入**：结构化特征、二分类响应标签、可选时间字段、禁用/泄漏风险字段列表。
- **任务类型**：二分类（首版只实现二分类；回归、聚类、时序留作扩展）。
- **主要业务指标**：`PR-AUC`，辅助 `ROC-AUC`、`F1`、`Precision@20%`、`Lift@20%`、规则覆盖率。
- **业务约束**：示例触达预算为 20%；实际通过 `top_fraction` 配置。
- **示例数据**：UCI Bank Marketing 数据集，可由使用者手动下载并指定路径；**禁止把互联网下载成功当作主流程的前置条件**。
- **离线兜底**：提供合成数据生成脚本，包含线性关系、特征交互、无关特征、缺失值，便于快速跑通和测试。

**真实数据注意事项：** Bank Marketing 的 `duration` 字段在联系客户之前不可用；若研究目标是“联系前选人”，应默认将该列列为禁用特征。不得因离线分数升高而将未来信息泄漏视为提升。

**因果边界：** 基于历史响应预测可评估排序和响应倾向，**不能直接声称营销触达带来了增量转化**。若无随机试验/合适的因果识别设计，报告必须避免因果收益宣称。

### 本场景下的“科研”必须体现

- 对表格数据提出**可证伪的统计或建模假设**，例如“某变量与标签呈非线性关系”或“两个变量存在交互”。
- 实验使用有效对照：相同数据切分、指标、随机种子与预处理隔离。
- 根据实验结果调整下一轮路线，例如发现交互特征无效后转向类别不平衡或子群体研究。
- 对关键结论做验证：置信区间、独立测试或跨切分稳定性。

---

## 3. 功能目标与优先级

| ID | Goal | 产物 | 验收条件 | 优先级 |
|---|---|---|---|---|
| G2 | 数据读取与 EDA | `dataset_profile.json` | 可读取 CSV/Parquet，识别缺失、类型、类别比例、潜在风险 | P0 |
| G3 | 基线训练 | `baseline_metrics.json` | 自动训练 Dummy + Logistic Regression，评估并记录 | P0 |
| G4 | 假设生成与管理 | `hypotheses.jsonl` | 每条假设含依据、预期、证伪条件、优先级 | P0 |
| G5 | 实验设计与执行 | `experiments.jsonl` | LLM 输出受约束实验配置；真实工具执行、超时可处理 | P0 |
| G6 | 科学验证与反证 | `reviews.jsonl` | 检查泄漏、过拟合、比较一致性、拒绝无效提升 | P0 |
| G7 | 反馈驱动迭代 | `decision_trace.jsonl` | 下一轮实验能引用上一轮结果，不是静态流水线 | P0 |
| G8 | 资源预算器 | `budget.json` | 达到上限停止；每次 LLM/实验调用都有消耗记录 | P0 |
| G9 | 报告与复现 | `report.md` + `run_manifest.json` | 包含基线、最好结果、失败记录、局限和复现方式 | P0 |
| G10 | 交互控制台 | Streamlit 页面 | 展示研究状态、假设树、实验轨迹、成本和报告 | P1 |
| G11 | 自动优化对照 | Optuna 小规模基线 | 与固定模型、随机搜索/Optuna 在同预算下比较 | P1 |
| G12 | 跨任务研究记忆 | `research_memory.jsonl` | 可复用策略，且有留一任务验证或 A/B 对照 | P2 |
| G13 | 开放式算法发现 | 受限特征表达式 DSL | 能安全生成、执行、测试新特征组合 | P2 |

**P0 是完整交付底线。没有 P0 不进行 P2。**

---

## 4. 技术栈（优先稳定与低资源）

| 层 | 技术 | 用途 |
|---|---|---|
| 语言 | Python 3.11+ | 全部后端逻辑 |
| Agent 状态编排 | LangGraph | 主循环、条件分支、状态恢复 |
| 数据契约 | Pydantic | 配置、假设、实验结果、工具参数的校验 |
| LLM | 主办方 API / 可配置 OpenAI-compatible API | 规划、假设、复杂解释、失败诊断 |
| 数据计算 | Pandas、NumPy | 数据读取、特征处理 |
| SQL 分析（可选） | DuckDB | 大表聚合和查询 |
| 统计推断 | SciPy、statsmodels | 检验、置信区间、回归分析 |
| 机器学习 | scikit-learn、LightGBM | 轻量分类基线与实验 |
| 超参实验 | Optuna | 受预算约束的对照优化 |
| 规则/关联挖掘（P1） | mlxtend | 关联规则、频繁项集 |
| 模型解释（P1） | SHAP | 提供候选假设的参考证据，不作为因果证明 |
| 持久化 | SQLite + JSONL | 研究状态、实验日志、预算审计 |
| 前端 | Streamlit + Plotly | 原型控制台 |
| 测试 | pytest | 单元、集成、端到端测试 |
| 隔离（可选） | Docker | 工具执行资源约束与隔离 |

**明确不选：** Kubernetes、Ray 集群、复杂多模型部署、分布式训练、重型 AutoML 平台作为研究主体、需要 GPU 的深度学习训练。

### Agent 职责，不等于 Agent 模型个数

1. `ResearchDirector`：管理当前研究目标、假设、状态与下一步决策。
2. `DataScientist`：通过确定性工具进行 EDA，发现值得验证的现象。
3. `HypothesisScientist`：基于证据提出可证伪假设，并给出实验策略。
4. `AlgorithmEngineer`：将假设转换为受控 ExperimentSpec 并执行。
5. `ScientificReviewer`：复核方法、泄漏、统计不确定性与反证。
6. `BudgetGovernor`：**确定性代码模块**，拦截超预算操作，不依赖 LLM 自觉遵守。

首版可以共享一个 LLM 提供者；**仅在需要新研究判断时调用 LLM**，不能每轮强制调用所有角色。

---

## 5. 系统架构与执行工作流

```text
CLI / Streamlit
      |
      v
TaskConfig -> Dataset Registry -> Safe Train/Validation/Test Split
      |
      v
ResearchDirector (LangGraph + Checkpoint)
      |
      +--> DataScientist --------> EDA / diagnostics (Python)
      |                                   |
      +--> HypothesisScientist <--------- evidence
      |         |
      |         v
      +--> ExperimentPlanner ----> Pydantic ExperimentSpec
      |                                   |
      |                              BudgetGovernor
      |                                   |
      |                                   v
      +--> ExperimentExecutor ----> sklearn / LightGBM / SciPy
      |                                   |
      +--> ScientificReviewer <---- real metrics & predictions
      |         |
      |         v
      +--> Decision: accept / reject / revise / stop
      |         |
      +---------+---------> next iteration (when budgets permit)
      |
      v
Final locked candidate -> Sealed test evaluation (once)
      |
      v
Research Registry -> report.md / metrics.json / plots / manifest
```

### 状态机节点（最小实现）

`initialize → profile → baseline → hypothesize → plan_experiment → budget_check → execute → review → decide → [hypothesize / plan_experiment / finish] → final_evaluate → export`

`budget_check` 必须在实际 API/实验调用之前执行；`finish` 不得重新触发实验；循环应设置 `max_iterations` 与终止原因。

### 终止条件

任意一种满足就结束：

- 达到用户指定目标且完成必要验证；
- Token / API 请求数 / 实验次数 / 总时间 / CPU 时间预算耗尽；
- 连续 `no_improvement_patience` 轮未发现有价值的新证据或改善；
- 数据或运行环境无法支持有效实验（明确报告原因）；
- 任务用户手动终止。

---

## 6. 核心数据契约与工具接口

### 6.1 TaskConfig（实例）

```yaml
project_name: signalmine-demo
dataset:
  path: data/marketing.csv
  format: csv
  target: y
  task_type: binary_classification
  forbidden_features: [duration]
  time_column: null
  positive_label: "yes"
objective:
  primary_metric: average_precision
  secondary_metrics: [roc_auc, f1, precision_at_k, lift_at_k]
  top_fraction: 0.20
  optimization: maximize
validation:
  strategy: stratified_holdout  # optional: temporal_holdout if time_column is available
  train_fraction: 0.60
  val_fraction: 0.20
  test_fraction: 0.20
  random_seed: 42
budget:
  max_llm_input_tokens: 12000
  max_llm_output_tokens: 4000
  max_llm_calls: 20
  max_experiments: 12
  max_wall_time_seconds: 900
  max_single_experiment_seconds: 90
  max_cpu_seconds: 600
  max_api_cost_usd: null  # when reliable pricing config is supplied
research:
  max_hypotheses: 6
  min_required_experiments: 3  # best effort, hard budget takes precedence
  no_improvement_patience: 3
  allow_advanced_models: true
llm:
  provider: configured_api
  model: ${MODEL_NAME}
  allow_mock: false
```

**注意：** 上述值只是可运行的 MVP 默认预算，不是赛方指定资源上限；配置中的环境变量需由加载器显式解析，禁止把 `${MODEL_NAME}` 原样传给 API。若实际 API 支持的模型不同，以赛方要求为准。

### 6.2 研究假设结构（HypothesisSpec）

```python
class HypothesisSpec(BaseModel):
    id: str
    claim: str                     # 可证伪命题
    observations: list[str]        # 对应已有证据 ID
    predicted_effect: str          # 对实验结果的预期
    falsification_condition: str   # 如何判定假设不成立/不被支持
    experiment_type: str           # 允许的实验模板类型
    estimated_cost: float | None = None
    status: Literal["proposed", "testing", "supported", "rejected", "inconclusive"]
```

### 6.3 实验结构（ExperimentSpec）

至少包含：`id`、`hypothesis_id`、`experiment_type`、`data_features`、`preprocessing`、`model_name`、`model_params`、`validation_policy`、`metric`、`random_seed`、`timeout_seconds`。

所有字段由 Pydantic 校验；`model_name` 和 `experiment_type` 使用白名单，`model_params` 使用限值，禁止未经授权访问封存测试集。

### 6.4 工具接口

```python
profile_dataset(dataset_id) -> DatasetProfile
run_baseline(task_id) -> ExperimentResult
propose_hypotheses(evidence, budget) -> list[HypothesisSpec]
plan_experiment(hypothesis, evidence, budget) -> ExperimentSpec
run_statistical_test(test_spec) -> StatisticalResult
run_experiment(experiment_spec) -> ExperimentResult
compare_experiments(experiment_ids) -> ComparisonResult
review_evidence(hypothesis_id, experiment_ids) -> ReviewResult
get_budget() -> BudgetSnapshot
finalize_research(task_id) -> ResearchReport
```

LLM 只能选择/填写受控工具参数，不可编造工具返回值。

---

## 7. 实验方法学硬约束

### 7.1 数据划分与泄漏控制

- 默认使用固定随机种子的分层 `train/val/test = 60/20/20`；有时间字段及时间依赖场景则使用时间切分。
- 缺失值填充、标准化、编码、特征选择等均在 Pipeline 内仅拟合训练数据。
- 验证集可用于研究和模型选择，**测试集只在最终方案冻结后评估一次**。
- 严禁把 `target`、目标衍生字段、已知决策后才能得到的字段加入预测特征。
- 若需要重复统计显著性分析，注明多重比较与模型选择偏差；报告不能假装一系列探索性 p 值是确认性检验。

### 7.2 基线与合法比较

- Baseline-0：DummyClassifier（验证任务是否优于常数预测）。
- Baseline-1：LogisticRegression + 适当预处理。
- Candidate：交互特征实验、非线性模型/LightGBM、类别不平衡处理、子群体策略等。
- 所有候选模型使用同一分割与评价协议，实验参数完整记录。
- `Precision@20%` 基于预测分数排序选前 20%，并报告真实覆盖人数、命中率；`Lift@20% = Precision@20% / 整体正样本率`（基准率不为 0 时）。
- 按验证集选“当前最优”不等于已证实提升；最终通过封存测试集检查泛化。

### 7.3 假设驱动实验模板（先做这四种）

1. `feature_interaction`：增加少量具可解释性的交互特征，和同基线比较。
2. `nonlinear_model`：以树模型检验线性模型不能捕获的关系。
3. `class_imbalance`：评估 class weighting、决策阈值与业务排序指标的不同影响（阈值变化不应声称改善 PR-AUC）。
4. `segment_discovery`：发现候选高响应子群体，检查最小样本数、规则覆盖与验证稳定性。

每种实验必须写明：**为什么做、预测会观察到什么、什么结果会否定该假设、实验后的下一步决定**。

### 7.4 统计验证

- PR-AUC 等核心指标使用适当的重复/Bootstrap 估计不确定性；小样本或时间相关数据要明确限制。
- 对多个候选特征/规则进行探索性比较时，考虑多重检验校正，避免挑选偶然最佳结果。
- 发现数据相关性只能称“关联”或“预测信号”，不能未经验证声称因果关系。
- 如果模型表现没有稳定提升，写出“未证实改善”，保留失败实验和结论。

---

## 8. Token 与实验资源管理（重点赛题能力）

### G8-A：多维硬预算

预算至少包含：`input_tokens`、`output_tokens`、`llm_calls`、`api_cost_usd（可选）`、`experiment_count`、`wall_time`、`cpu_time`。

- 调用前先检查剩余额度；当某一关键额度不足时，选择较低成本的合法操作或停止。
- 如果 API 返回实际 token usage，优先采纳；否则按 tokenizer 估计并打上标记。
- 实验计时、CPU 时间使用运行环境测量；超时自动中断并记录。
- 不允许将 Token 费用与本地 CPU 成本混为一个未经定义的总成本；应分别展示，必要时给出可调整的权重。
- 若没有价格表，只报告 Token 数和已知费用，**不得凭空给出美元金额**。

### G8-B：动态研究调度（MVP 先用确定性启发式）

研究策略优先级综合以下因素：

- `expected_information_gain`：实验预计能区分多少竞争假设；
- `expected_metric_gain`：预计能改善多少业务指标；
- `experiment_cost`：预计运行时间/计算量；
- `llm_cost`：新增分析调用的 Token 预算；
- `risk`：数据泄漏、无效检验、过拟合可能性。

先实现可解释的规则路由，不必一开始训练强化学习路由器。

**升级高成本推理的触发条件**（如比赛只提供一个模型，则把“升级”实现为更精细的上下文和追加推理调用）：

- 连续多个实验没有得到可解释结果；
- 关键假设存在冲突，需要提出新实验；
- 不同实验结果高度矛盾，确定性检查没有定位原因；
- 预期收益足够高且剩余额度允许。

规则：优先将实验指标、错误摘要和关键证据压缩后送入 LLM，**不得每轮发送完整数据集或全部历史对话**。

---

## 9. 系统评估：重点评的是 Agent，不只是模型分数

### 必须比较的四种方法

| 组别 | 研究策略 | 用途 |
|---|---|---|
| A：Fixed Pipeline | 固定 EDA + Logistic Regression/LightGBM | 测试最简单的自动化基线 |
| B：Optuna Baseline | 固定模型族 + 有界超参搜索 | 测试普通优化器能做到什么 |
| C：Single Agent | 同一个 LLM，不引入明确假设/反证角色 | 测试一般 Agent 水平 |
| D：SignalMine | 假设驱动 + 反证 + 资源调度 + 研究记忆（按阶段开启） | 测试本系统的价值 |

**公平性要求：** 固定数据划分、硬件、核心算法可用范围及总体实验资源；所有对照报告自己的 LLM Token/调用量、耗时和模型质量。若算法或预算不完全相同，需要明确披露。

### 必报指标

| 类别 | 指标 | 如何获得 |
|---|---|---|
| 模型质量 | PR-AUC、ROC-AUC、F1、Precision@20%、Lift@20% | 真实预测和标签计算 |
| 研究效率 | 有效实验数、总实验数、达到目标所需轮次 | Experiment Registry |
| 成本 | LLM 输入/输出 Token、调用次数、已知 API 费用 | Model Gateway |
| 时间 | 端到端总耗时、实验耗时、LLM 等待耗时 | 计时器与日志 |
| 科研严谨性 | 反证次数、泄漏阻断次数、无效结论拒绝次数 | Review Registry |
| 可复现性 | 固定环境下是否可复现，以及产物完整率 | 复现脚本 + 验收脚本 |

### 消融测试（P1）

- 移除 ScientificReviewer：衡量误接受无效研究的变化。
- 移除 BudgetGovernor 的动态策略（保留硬上限）：衡量 Token/时间成本变化。
- 移除历史研究记忆：衡量跨数据集任务效率变化。

**不要以“多 Agent 越多越好”作为卖点，必须用消融实验证明角色分工带来了价值。**

---

## 10. 建议的代码目录

```text
signalmine/
├── README.md
├── pyproject.toml
├── configs/
│   ├── demo.yaml
│   └── competition.yaml
├── data/
│   ├── README.md
│   └── synthetic_demo.csv         # generate_demo_data.py 创建
├── src/signalmine/
│   ├── cli.py
│   ├── config.py
│   ├── schemas.py
│   ├── graph.py
│   ├── agents/
│   │   ├── director.py
│   │   ├── data_scientist.py
│   │   ├── hypothesis.py
│   │   ├── algorithm.py
│   │   └── reviewer.py
│   ├── tools/
│   │   ├── data_profile.py
│   │   ├── statistics.py
│   │   ├── preprocessing.py
│   │   ├── models.py
│   │   └── experiments.py
│   ├── orchestration/
│   │   ├── budget.py
│   │   ├── llm_gateway.py
│   │   ├── registry.py
│   │   └── memory.py
│   ├── evaluation/
│   │   ├── metrics.py
│   │   ├── baselines.py
│   │   └── reporting.py
│   └── app.py
├── scripts/
│   ├── generate_demo_data.py
│   ├── reproduce_run.py
│   └── benchmark_agents.py
├── tests/
│   ├── test_budget.py
│   ├── test_leakage.py
│   ├── test_experiments.py
│   ├── test_research_loop.py
│   └── test_report.py
├── runs/                        # 每次研究新建独立 run_id 目录
└── PROGRESS.md
```

结构可按实现简化，但职责分离与 `runs/<run_id>` 可追溯产物必须保留。

---

## 11. 分阶段实施计划与 Stop/Go 条件

### Phase 1 — 可运行数据科学基线（P0）

**Goal：** 接受数据配置，生成 EDA 与 Baseline 指标。

任务：

- 初始化 Python 包、依赖管理、pytest；
- 实现合成数据生成，支持本地 CSV；
- 实现合法的数据划分与禁用特征名单；
- 训练 Dummy 与 LogisticRegression，输出指标；
- 输出 `dataset_profile.json` 和 `baseline_metrics.json`。

**Gate：** `pytest` 通过；CLI 对合成数据能端到端输出真实基线结果。未通过不得开始复杂 Agent。

### Phase 2 — 最小自主研究闭环（P0）

**Goal：** Agent 根据证据提出假设、调用至少两类实验模板、根据结果选择下一步。

任务：

- 定义 HypothesisSpec / ExperimentSpec / ExperimentResult；
- 实现 LangGraph 研究状态机；
- 实现 `feature_interaction` 和 `nonlinear_model` 模板；
- 实现 ReviewResult：`accept/reject/inconclusive`；
- 记录每轮研究前后的理由和引用证据 ID；
- 支持真实 LLM 和 Mock LLM 两种执行模式。

**Gate：** 受控测试案例中，实验真实执行；Agent 能根据不同反馈走不同分支；日志可重建因果链路。

### Phase 3 — 预算约束与科研审查（P0）

**Goal：** 任意预算耗尽时安全停止，并对研究结论做基本科学复核。

任务：

- Token/调用数/时间/实验次数预算拦截；
- 训练与验证泄漏检查；
- 统计检验、Bootstrap（适用时）、结果不确定性报告；
- 支持实验失败、模型接口报错、超时和恢复；
- 做一次完整研究任务并导出报告。

**Gate：** 极低预算测试不超限；人为注入泄漏字段的测试能够阻止无效使用；实验失败不导致整体状态丢失。

### Phase 4 — 竞赛评估与交互展示（P1）

**Goal：** 评委能看清研究过程，能够对比不同方案的 Token、时间和质量。

任务：

- Streamlit：任务配置、实时状态、假设列表、指标变化、预算计量；
- 对照组：Fixed Pipeline、Optuna、Single Agent；
- 记录固定种子下的实验结果与总运行时长；
- 完成 1 个公开数据实例 + 1 个合成数据实例（公开数据下载不稳定时说明情况）。

**Gate：** 无需手工编辑源码即可启动 Demo；对照表数值全部来自真实实验。

### Phase 5 — 有余力时再做（P2）

- 跨任务策略记忆及有效性验证；
- 规则挖掘/受控特征表达式 DSL；
- 多任务支持（回归、异常检测）；
- 更复杂的主动实验选择算法。

**禁止抢跑 P2 导致 P0 不可运行。**

---

## 12. CLI 与报告交付协议

实现至少如下命令（命令名若调整须同步 README）：

```bash
# 安装
python -m pip install -e '.[dev]'

# 生成离线演示数据
python scripts/generate_demo_data.py --output data/synthetic_demo.csv

# 无云端 API 的集成测试 / 演示模式
signalmine run --config configs/demo.yaml --llm mock

# 接入真实云端 LLM（API Key 从环境变量读取）
signalmine run --config configs/demo.yaml --llm api

# 对照评测
python scripts/benchmark_agents.py --config configs/demo.yaml

# 复现某次运行
python scripts/reproduce_run.py --run-id <RUN_ID>

# 运行测试
pytest -q

# 可视化
streamlit run src/signalmine/app.py
```

一次成功/有界停止的研究运行，应在 `runs/<run_id>/` 下生成：

```text
run_manifest.json
config.resolved.yaml
dataset_profile.json
baseline_metrics.json
hypotheses.jsonl
experiments.jsonl
reviews.jsonl
decision_trace.jsonl
budget.json
best_model.joblib             # 若有有效模型
predictions_test.csv          # 最终测试已合法执行时
report.md
```

### 最终报告 `report.md` 必含

1. 研究任务与业务约束；
2. 数据摘要、数据泄漏检查和划分协议；
3. 研究假设及证据来源；
4. 完整实验对比（包含失败尝试）；
5. 保留/否决假设的理由；
6. 最好候选模型与最终测试表现；
7. 指标的不确定性、研究局限与禁止过度推断的说明；
8. Token/费用/实验次数/CPU 时间/总耗时；
9. 复现实验命令、随机种子、数据与环境指纹；
10. 如未达到目标，写清未达成原因与下一轮研究建议。

---

## 13. 自动化测试清单（Agent 必须落地）

- [ ] `test_budget.py`：总 Token 上限、请求次数、实验次数、超时约束生效。
- [ ] `test_leakage.py`：禁用字段不可进入模型；训练/验证/测试间预处理不泄漏。
- [ ] `test_experiments.py`：合法 ExperimentSpec 可执行；非法参数被拒绝；失败可记录。
- [ ] `test_research_loop.py`：不同实验反馈导致不同策略分支；可主动停止；无死循环。
- [ ] `test_report.py`：报告数值与 Registry 一致；不允许缺失来源却宣称实验结果。
- [ ] 一份小合成数据在无 API 环境下完成全流程集成测试。
- [ ] 使用真实 API 的演示能显示实际调用记录（仅在 API 可用时）。
- [ ] 所有实验记录包含 `run_id`、`experiment_id`、配置哈希与耗时。

---

## 14. 交付标准：Definition of Done

只有满足下面全部条目，才允许将项目标记为 MVP 完成：

- [ ] 有一条从输入数据到报告输出的**真实可运行研究闭环**。
- [ ] 至少两种非等价研究假设与三次真实实验（当给定预算允许）。
- [ ] Agent 可以依据实验反馈修改研究计划，而非只顺序执行固定脚本。
- [ ] 封存测试集与泄漏保护可由自动测试证明。
- [ ] 有硬预算、成本记录、到上限自动停止机制。
- [ ] 有失败实验、拒绝假设、无法改进时的有效报告路径。
- [ ] 有可复现运行记录和可查看的研究轨迹。
- [ ] 通过自动测试，README 含从零运行步骤。
- [ ] 研究结果和对比基线均为真实计算结果，无伪造数字。

### Agent 每轮开发任务结束必须汇报的内容

```text
[Completed]
- 本轮实现的功能：
- 修改/新增文件：
- 运行的命令：
- 测试结果：
- 示例研究运行 ID：

[Next]
- 下一项最高优先级 Goal：

[Blockers / Risks]
- 仍未解决的问题：
- 对比赛交付的影响：
```

---

## 15. 启动执行命令（直接给编码 Agent）

**现在开始实际开发，不要只写方案。**

1. 检查现有项目文件；如果为空，从 Phase 1 初始化。
2. 优先完成 P0：合法数据处理、真实实验执行、假设与反馈循环、成本硬约束、报告导出。
3. 对每个目标执行“实现 → 测试 → 记录失败 → 修复 → 再测”，直到 Gate 通过。
4. 如无互联网、无 API Key 或无 GPU，不停止项目：使用离线合成数据、Mock LLM 和 CPU 模型完成可验证主链路；注明 Mock 模式与真实 Agent 表现的区别。
5. 任何时候发现开发进度不足，优先砍掉 P1/P2，不得牺牲数据泄漏保护、真实实验、预算机制或可复现性。
6. 完成后输出可运行仓库、所有测试结果、至少一次研究 run 的产物和最终 README。

**最终目标：以尽可能少的 Token、计算时间和实验次数，让 Research Agent 自主找到“被证据支持的有效规律或更优模型”，并能说明为什么可信；如果找不到，也能严格、诚实地证明研究已按预算完成。**
