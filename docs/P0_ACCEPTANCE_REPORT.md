# G0 / P0 终验收报告

日期：2026-11-14。依据：[RESEARCH_AGENT_GOALS.md](RESEARCH_AGENT_GOALS.md)（G0 验收标准 1–9）、[P0_IMPLEMENTATION.md](P0_IMPLEMENTATION.md)。验收证据在 `runs/p0-acceptance-20261114` 与 `runs/p0-acceptance-replay-20261114`，真实联调记录在 `runs/p0-api-20261114` 与 `runs/p0-api-contract-20261114`（运行目录可能含用户数据，不提交 Git）。

## 1. 结论

- **G0 / P0 通过验收**：单命令自主研究闭环、真实计算实验、统计审查、证据驱动决策、预算与一次性封存测试、完整报告与可复现性均按验收标准逐条验证（第 5 节）。
- 验收示例采用 **Mock 研究决策 + 真实科学计算**；Mock 模式在报告与 manifest 明示，不宣称真实 LLM 科研能力。
- 真实 LLM 联调冒烟**已通过**（第 6 节）：云端 deepseek-v4-pro 完成研究规划并获采纳，本地 qwen2.5:1.5b（Ollama）完成 3 次候选排序，全流程研究闭环端到端跑通；Token 实际对账，封存测试结果与 Mock 验收示例一致。

## 2. 验收示例：4 假设、7 次真实计算实验

运行目录 `runs/p0-acceptance-20261114`，配置 [configs/demo.yaml](../configs/demo.yaml)（分层 60/20/20、种子 42、主指标 Average Precision、top 20%、预算 8 实验 / 120 CPU 秒 / 180 墙钟秒、Mock、0 次 LLM 调用额度）。

指纹：

- 数据 SHA-256 `8c4eecde…3f93668`；600 行，训练画像 360 行，正类率 0.3278；禁用字段 `duration`、`y`；未检出目标副本列。
- 配置哈希 `3de84c82…e37532`；科学模块源码哈希 `d5b8f685…3e946f`（与当前工作树一致）。
- 环境：Python 3.12.4；numpy 2.5.4、pandas 3.1.1、scikit-learn 1.9.1、scipy 1.18.1、langgraph 1.2.21、pyarrow 26.0.1。
- 停止原因：`hypotheses_exhausted`（全部假设均已实验与审查）。

### 假设（4 条，另加 1 条基线对照）

| 假设 | 断言摘要 | 实验模板 | 结论 |
|---|---|---|---|
| h-feature_interaction | 特征交互超出加性逻辑回归的预测信号 | feature_interaction | supported |
| h-class_imbalance | 类别权重改善不平衡下的排序 | class_imbalance | inconclusive |
| h-nonlinear_model | 有界树集成捕获线性模型漏掉的非线性 | nonlinear_model | supported |
| h-segment_discovery | 训练选定子群体在验证集上有稳定高响应 | segment_discovery | rejected |

### 实验、审查与决策（7 次实验，含最终测试）

| 实验 | 假设 | 配置哈希 | 验证 AP | 审查 | 决策 |
|---|---|---|---|---|---|
| baseline-dummy | baseline-control | 1f2b6d33… | 0.333333 | —（对照） | retain_control |
| baseline-logistic | baseline-control | 50fa861f… | 0.450410 | —（对照） | retain_control |
| experiment-1 | h-feature_interaction | 9956dd65… | 0.807724 | accept（Δ 区间 [0.2226, 0.4657]） | continue |
| experiment-2 | h-class_imbalance | 99810db7… | 0.453487 | inconclusive（Δ 区间 [-0.0269, 0.0386]） | continue |
| experiment-3 | h-nonlinear_model | 1d684412… | 0.649403 | accept（Δ 区间 [0.0416, 0.3334]） | continue |
| experiment-4 | h-segment_discovery | 5850e010… | 0.450410 | reject（Δ 区间 [0.0, 0.0]） | stop（hypotheses_exhausted） |
| final-test | experiment-1（冻结） | 79bb97e3… | —（封存测试，见下） | — | — |

每一行构成 `hypothesis_id → experiment_id → config_hash → metrics → review → decision` 完整关联，原始记录见 `hypotheses.jsonl`、`experiments.jsonl`、`reviews.jsonl`、`decision_trace.jsonl`。

### 冻结方案与一次性封存测试

- 冻结候选：experiment-1（验证 AP 0.807724；选择规则：验证 AP 最大，平局按实验顺序）。
- 封存测试（`test_metrics.json` / `predictions_test.csv`，120 个测试样本）：

| AP | ROC-AUC | F1 | Precision@20% | Lift@20% |
|---|---|---|---|---|
| 0.699028 | 0.786008 | 0.563380 | 0.708333 | 2.179487 |

- 测试 AP Bootstrap 95% 区间 [0.610167, 0.802581]。
- 测试权限先持久化消费、后读取封存测试（`test_evaluations: 1`）；封存测试只检查冻结模型泛化，不据此声称超过未在测试集评估的基线。

### 资源使用（budget.json）

0 次 LLM 调用（Mock 模式）；实验 7 次（含最终评估）；科学计算 CPU 30.84375 秒全部实测；墙钟 42.854 秒；API 费用 $0。全部 8 条操作记录 `settled` + `measured`，无虚构零消耗。

## 3. 完整复现

`runs/p0-acceptance-replay-20261114`（`reproduce` 命令重放，独立目录，不覆盖原研究）：

- 配置哈希、数据 SHA-256、科学模块源码哈希、种子 42、环境版本与验收运行完全一致。
- `reproduction_comparison.json`：6 个实验的 8 项指标差**全部为 0**（`same_metrics: true`）；最终测试 `candidate_id / metrics / predictions / labels / error` **全部一致**（`matches: true`）。
- 冻结候选一致（experiment-1，验证 AP 0.807724）；复现不重新请求模型。

## 4. 产物审计

- **关联链**：每个实验记录含 `hypothesis_id`、`config_hash`、指标与耗时；审查记录指向实验；决策记录通过 `evidence_ids` 引用审查或实验。
- **报告数值回溯**：report.md 中全部指标、差值区间与预测可逐项对应 `experiments.jsonl` / `test_metrics.json` / `predictions_test.csv`，无手工数字。
- **预算账目**：budget.json 逐操作记录；API 运行用量缺失时保留预留并标记 unknown，不编造计费（第 6 节）。
- **封存测试只消费一次**：test_gate 在读取测试前持久化消费，崩溃后不重复打开测试（测试覆盖 `test_consumed_gate_cannot_reopen_test_after_crash`）。
- **失败与无改善是合法结果**：h-class_imbalance 未证实、h-segment_discovery 被拒绝，报告如实保留，不把失败改写为提升。

## 5. G0 验收标准逐条对照

| # | 验收标准 | 证据 |
|---|---|---|
| 1 | 单条 CLI 命令启动自主研究至停止条件 | `python -m lazyresearch.science run --config configs/demo.yaml --llm mock`；停止原因 `hypotheses_exhausted`；CLI 暴露 run/resume/reproduce（`test_run_resume_reproduce_commands_are_exposed`） |
| 2 | 基线 + ≥2 实质区别假设 + ≥3 真实实验 | 2 基线（Dummy/LR）+ 4 假设（交互/不平衡/非线性/子群体）+ 4 假设实验，全部真实训练与指标 |
| 3 | 实验完整关联链 | 第 2 节审计表；原始 JSONL 逐条可查 |
| 4 | 至少一次基于真实结果的决策 | decision_trace：decision-1/2/3 continue（引用 review-experiment-1/2/3），decision-4 stop（引用 review-experiment-4） |
| 5 | 固定协议报告且数值可回溯 | report.md 由 reporting 模块生成；第 4 节审计 |
| 6 | 真实 LLM Token 对账；缺失标未知 | 双模型冒烟：云端 1 次 + 本地 3 次共 4 次调用，输入 2492 / 输出 246 Token 实际对账；无价格表时费用标 unknown，不编造 |
| 7 | 预算耗尽后停止收费与计算，仍导出成果 | 预算测试 6 项；零预算仍导出（`test_zero_budget_still_exports`）；API 模式预算耗尽即停止（`test_api_mode_exhausted_calls_stop_compute_but_mock_zero_calls_allowed`） |
| 8 | 同数据/划分/种子/配置可复现 | 第 3 节完整复现：指标差全 0，最终测试预测一致 |
| 9 | CLI/JSON/Markdown 报告先行 | [SCIENCE_DEPLOYMENT.md](SCIENCE_DEPLOYMENT.md) 与 [SCIENCE_WORKFLOW.md](SCIENCE_WORKFLOW.md)；现有 Web 保留 fixture 工作台 |

## 6. 真实联调（API）证据与限制

### 双模型冒烟（2026-11-14，已通过）

运行目录 `runs/p0-dualmodel-smoke-20261114`，配置 [configs/smoke.yaml](../configs/smoke.yaml)（`provider: configured_api`、`allow_mock: false`、预算放宽到 6 次调用 / 900 墙钟秒），模型配置 models.toml（云端 deepseek-v4-pro，本地 Ollama qwen2.5:1.5b）。

| 调用 | 角色/模型 | 耗时 | 结果 |
|---|---|---|---|
| research-plan | cloud / deepseek-v4-pro | 10.0 s | 返回 `hypothesis_ids: [h-feature_interaction, h-nonlinear_model, h-class_imbalance, h-segment_discovery]`，**通过硬校验并被采纳** |
| selection-1 | local / qwen2.5:1.5b | 5.2 s | 选中 h-feature_interaction（有效候选） |
| selection-2 | local / qwen2.5:1.5b | 0.6 s | 选中 h-class_imbalance（有效候选） |
| selection-3 | local / qwen2.5:1.5b | 0.8 s | 选中 h-segment_discovery（有效候选） |

- 4 次调用全部完成：输入 Token 2492、输出 Token 246 实际对账，未知用量 0；无可靠价格表，API 美元费用保持 unknown。
- 全流程：2 基线 + 4 假设实验 + 1 封存测试共 7 次真实计算；停止原因 `hypotheses_exhausted`；CPU 21.44 秒、墙钟 48.56 秒。
- 假设结论与 Mock 验收示例一致（交互/非线性 supported、类别权重 inconclusive、子群体 rejected）；冻结 experiment-1；**封存测试 AP 0.699028 与 Mock 验收运行逐位一致**，说明模型路由不改变确定性科学计算。
- 本机系统代理（127.0.0.1:7897）在冒烟时不可用，云端直连可达；网关对云端默认跟随系统代理，本次以 `NO_PROXY="*"` 绕过。日常使用需修复代理或保持直连。

### 早期冒烟（已记录的历史限制）

`runs/p0-api-20261114` 与 `runs/p0-api-contract-20261114`（均为旧版科学模块源码）两次均以 `model_planning_failed` 停止：一次云端调用成功（949/1194 Token、19.45 秒）但计划未通过硬校验，一次 `ConnectError`。两次均按设计交付基线 + 基线封存测试（测试 AP 0.412122），未伪造研究结论。新版网关把卡片 ID 契约收紧进 `ResearchPlan` schema 后，上述失败不再复现。

### 剩余限制（如实记录）

1. 本版本只允许模型从预生成候选卡片中选牌，不生成任意算法代码；模型只提供研究决策，指标全部由确定性工具计算。
2. 无价格表时费用保持 unknown；若任务同时配置美元硬上限，系统拒绝不可定价的云调用（测试覆盖）。
3. 配置 API 模式不会默认伪装为 Mock；只有 `allow_mock: true` 才回退并在报告标识。
4. 受限终端（沙箱禁止回环/外联）可能阻断真实联调；冒烟需在具备网络的终端执行。
5. 云端按部署文档设 `max_output_tokens=512`、timeout 60 秒；超时与失败保留预留并记录，不重试结果不明的调用。

## 7. 测试证据

2026-11-14 本机完整套件（允许回环连接的终端）：

**47 passed, 4 subtests passed（115.51 秒）**

| 模块 | 数量 | 覆盖 |
|---|---|---|
| test_science_budget | 6 | 预留持久化、未知用量、对账、超限停止、不可定价拒绝 |
| test_science_gateway | 7 | 真实用量对账、失败保留预留、总期限、定价、选牌校验、用户停止 |
| test_science_data | 5 | 划分可复现互斥、泄漏阻断、Parquet/时间切分、训练集预处理隔离 |
| test_science_execution | 5 | 子进程成功/失败/复用、超时终止、停止、不确定操作不重跑、并发锁 |
| test_science_roles | 4 | 可证伪假设、审查拒绝与协议检查、受控计划、最少实验目标 |
| test_science_loop | 4 | 真实实验主循环与恢复、零预算导出、失败可恢复、错误不吞 |
| test_science_final | 3 | 冻结一次、低预算跳过、测试门消费后崩溃不重开 |
| test_science_experiments | 3 | 真基线与受控模板、非法参数拒绝、top-k 指标与排序一致 |
| test_science_reproduction | 1 | 最终比较拒绝失败或改动测试 |
| test_science_cli | 1 | run/resume/reproduce 命令暴露 |
| test_model_config | 2 | 配置优先级、双 HTTP 端点（4 子测试） |
| test_workbench | 6 | 原 fixture 工作台回归：事件回放、云端准入、循环、恢复、工具预算 |

## 8. 边界与不宣称

- 仅预测响应倾向/排序，不推断因果增量；无随机试验设计时不作因果收益宣称。
- 验收示例为 Mock 研究决策 + 真实科学计算；**不宣称真实 LLM 科研能力**。
- 自动泄漏检查不完整；业务禁用字段必须由用户提供（示例默认禁用 `duration`）。
- P1（Streamlit 控制台、Optuna 对照）、P2（跨任务记忆）、G13（开放特征 DSL）不在本轮交付范围。
- 探索性多重比较使用调整区间，仍受自适应选择偏差影响；小样本或时间相关数据的 IID Bootstrap 可能偏乐观。

## 9. 证据索引与复现命令

| 对象 | 位置 |
|---|---|
| 验收示例 | `runs/p0-acceptance-20261114/`（run_manifest.json、report.md、experiments.jsonl、…） |
| 完整复现 | `runs/p0-acceptance-replay-20261114/`（reproduction_comparison.json） |
| 双模型冒烟 | `runs/p0-dualmodel-smoke-20261114/`（model_calls.jsonl 含 1 次云端规划 + 3 次本地选择） |
| 早期联调记录 | `runs/p0-api-20261114/`、`runs/p0-api-contract-20261114/` |
| 部署与运行 | [SCIENCE_DEPLOYMENT.md](SCIENCE_DEPLOYMENT.md)、[SCIENCE_WORKFLOW.md](SCIENCE_WORKFLOW.md) |
| 实施清单 | [P0_IMPLEMENTATION.md](P0_IMPLEMENTATION.md) |
| 进度记录 | [PROGRESS.md](../PROGRESS.md) |

```powershell
# 复现验收示例（创建独立目录，不覆盖原研究）
.\.venv\Scripts\python.exe -m lazyresearch.science reproduce --run-dir runs/p0-acceptance-20261114

# 完整测试
.\.venv\Scripts\python.exe -m pytest -q
```
