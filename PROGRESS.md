# G0 / P0 开发进度

## 2026-11-14：范围与现状核对

- 已将用户提供的原始任务书保存至 `docs/RESEARCH_AGENT_GOALS.md`。
- 已检查当前实现：LangGraph、SQLite、模型网关、CLI/Web 存在；仅注册 FixtureAdapter，没有真实表格研究能力。
- 实施与验收清单：`docs/P0_IMPLEMENTATION.md`。
- G0/P0 尚未完成；下一项为 Phase 1 数据契约、安全切分及真实基线。
- 本轮未运行研究任务，未产生可宣称的业务指标。

## Phase 1 实现与验证

- 新增 `lazyresearch/science/schemas.py`：类型化数据、目标、划分、预算与研究配置；YAML 环境变量显式解析。
- 新增 `data.py`：离线合成数据、CSV/Parquet、固定种子分层划分/时间划分、训练范围 EDA、禁用字段/二值标签副本阻断。
- 新增 `experiments.py`：训练集内拟合 Pipeline、Dummy/LR、交互/树模型/类别权重/子群体受控模板，以及真实预测指标。
- 科学计算依赖已安装到 `.venv`，声明在 `requirements.txt`。
- `python -m pytest tests/test_science_data.py tests/test_science_experiments.py -q`：7 passed。
- 基线诊断：`python -m lazyresearch.science baseline --config configs/demo.yaml --output runs/phase1-baseline-20261114`，真实验证集 AP：Dummy 0.3333333333333333，LR 0.45040969294254973；未评估测试集。
- 原始预测、指标、数据指纹与划分已保存在上述运行目录。该目录不是已完成的自主研究报告。
- 下一步：Phase 2 角色化 LangGraph 主循环，以及 Phase 3 进程级预算/恢复/封存测试；现有基线诊断尚不提供这些保证。
- 完整测试：`python -m pytest -q` 在允许本机回环连接的环境中完成，15 passed、4 subtests passed（10.56 秒）。受限环境的本地 HTTP 测试未正常返回，不能将该次运行视为通过；独立执行的完整套件已通过。

## Phase 2 / 3：角色、预算及真实执行闭环

- 新增 SQLite Registry 与 BudgetGovernor：调用前持久化预留，未知用量保留，重启不重置计量，实验/Token/请求/墙钟/CPU/费用限制。没有价格表时费用上限拒绝收费调用。
- 新增角色模块：DataScientist、HypothesisScientist、AlgorithmEngineer、ScientificReviewer、ResearchDirector；配对 Bootstrap 与探索性多重比较说明，真实反馈改变后续模板。
- 新增独立进程执行：超时终止、CPU watchdog、父进程消失后退出、结果复用、失败记录。不重跑恢复时结果不明的操作。
- 新增 LangGraph 研究主图及 SQLite checkpoint；完成真实实验、评审、决策、循环与低预算导出测试。
- 新增科学研究模型网关：复用 models.toml，云端生成结构化假设计划，本地选择后续假设，连续无改进可升级云端。输入/输出 Token 实际对账，未知使用保留；配置 API 模式不会默认伪装为 Mock。
- 已分别通过：预算 4 项、角色 3 项、进程执行 2 项、主循环 2 项、网关 2 项测试。
- 尚未完成：封存测试最终评估、完整报告/manifest 与复现、全流程 CLI/部署、EDA 计算的硬预算覆盖、并发运行互斥、子群体不确定性完善。当前报告明确标为 intermediate，不满足 G0/P0 最终交付。
- Ruling：保留现有 Web，科学研究首先交付 CLI/JSON/Markdown，符合 G0 条款 9；Streamlit 属 P1。

## 终验收与完整复现（2026-11-14）

- 验收示例 `runs/p0-acceptance-20261114`（Mock 决策 + 真实计算，configs/demo.yaml）：4 个研究假设、7 次真实计算实验（2 基线 + 4 假设实验 + 1 次封存测试），停止原因 hypotheses_exhausted。假设结论：交互 supported、非线性 supported、类别权重 inconclusive、子群体 rejected；冻结 experiment-1，封存测试 AP 0.699028（Bootstrap 95% [0.610167, 0.802581]）。
- 完整复现 `runs/p0-acceptance-replay-20261114`：配置/数据/源码哈希与验收运行一致；6 个实验 8 项指标差全 0，最终测试候选、指标、预测、标签全部一致；复现不重请求模型。
- 产物审计：每个实验的 hypothesis_id → config_hash → metrics → review → decision 关联逐条核对；report.md 数值可回溯到原始 JSONL；预算逐操作实测（CPU 30.84 秒、墙钟 42.85 秒、0 次 LLM 调用）。
- 真实联调 `runs/p0-api-20261114` / `runs/p0-api-contract-20261114`：deepseek-v4-pro 真实调用成功（949/1194 Token 实际对账），但云端计划未通过候选卡片精确 ID 硬校验，两次均以 model_planning_failed 停止并按设计交付基线 + 基线封存测试（测试 AP 0.412122）。真实 LLM 端到端研究闭环尚未演示成功，费用无价格表保持 unknown。限制已写入验收报告。
- 完整测试：`python -m pytest -q` 在允许本机回环连接的终端执行，47 passed、4 subtests passed（115.51 秒）。
- 终验收报告：`docs/P0_ACCEPTANCE_REPORT.md`；实施清单全部勾选：`docs/P0_IMPLEMENTATION.md`。运行目录已加入 .gitignore。
- 双模型冒烟（2026-11-14 通过）：`runs/p0-dualmodel-smoke-20261114`（configs/smoke.yaml）。云端 deepseek-v4-pro 规划被采纳（10.0 秒，hypothesis_ids 通过硬校验），本地 Ollama qwen2.5:1.5b 完成 3 次候选排序（5.2/0.6/0.8 秒）；共 4 次调用、输入 2492 / 输出 246 Token 实际对账、未知用量 0；7 次真实计算、停止原因 hypotheses_exhausted；封存测试 AP 0.699028 与 Mock 验收逐位一致。费用因无价格表保持 unknown。本机系统代理 127.0.0.1:7897 不可用，冒烟用 `NO_PROXY="*"` 直连云端；早期 `model_planning_failed` 由旧版契约导致，新版 schema 收紧后不复现。报告第 6 节已更新。
