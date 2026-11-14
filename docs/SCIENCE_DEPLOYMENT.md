# 表格研究部署、运行与验收

## 交付范围

G0 / P0：面向二分类表格数据的真实研究闭环。Python 3.11+、LangGraph、Pydantic、Pandas/NumPy、scikit-learn/SciPy、SQLite/JSONL。使用 CPU 上的受控树模型，无需 GPU、LightGBM 或分布式基础设施。现有 FastAPI/React 工作台继续运行 fixture 流程；表格研究的 CLI 与报告是本阶段正式入口。Streamlit、Optuna 对照、SHAP 和跨任务记忆留在 P1/P2。

## 从零部署

先按根 README 克隆代码；离线科学 Demo 不需要加载 GGUF。Windows 在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\deploy-research.ps1
```

`RemoteSigned` 仅作用于该 PowerShell 进程，不修改机器永久执行策略。脚本复用或创建 `.venv`，安装 `requirements.txt`，在默认数据缺失时生成合成数据，使用 `configs/demo.yaml` 完成真实研究并输出报告目录。重跑创建新目录，不覆盖原研究。

| 参数 | 用途 |
|---|---|
| `-SkipInstall` | 已安装依赖时复用环境 |
| `-PrepareOnly` | 只准备环境和默认数据 |
| `-RunTests` | 部署时运行完整测试 |
| `-TaskConfig configs/my-task.yaml` | 选择任务配置 |
| `-Llm mock` / `-Llm api` | 显式选择研究决策模式，默认 mock |
| `-ModelConfig models.toml` | 模型端点与密钥配置 |
| `-DeployLocalModel` | 委托已有部署脚本准备 Ollama/Qwen；该可选路径也会构建现有 Web，需要 Node.js |
| `-RunDir runs/my-run` | 指定尚不存在的产物目录 |
| `-Python C:\Python312\python.exe` | 创建虚拟环境时使用指定解释器 |

其他操作系统可以使用等价 Python 命令：

```bash
python -m venv .venv
# 激活虚拟环境后
python -m pip install -r requirements.txt
python -m lazyresearch.science generate-demo --output data/synthetic_demo.csv
python -m lazyresearch.science run --config configs/demo.yaml --llm mock
```

## 自有数据与预算

复制 `configs/demo.yaml`，修改 `dataset.path`、`target`、`positive_label`。数据相对路径以 YAML 文件所在目录为准。Parquet 设置 `format: parquet`。标签必须为无缺失二分类；需要训练、验证、测试每部分同时包含两类。默认分层 60/20/20、种子 42；时间场景设置 `validation.strategy: temporal_holdout` 和 `dataset.time_column`，边界相同时间戳会被拒绝，避免跨边界混合。

`forbidden_features` 必须列出业务上不可用的未来字段或目标派生字段，默认含 `duration`。自动检测明显二值目标副本只是辅助，不能证明业务字段无泄漏。预处理仅拟合训练数据；研究阶段不对测试集做画像或模型选择。

预算字段见任务书与 `ScienceBudget`：输入/输出 Token、调用次数、实验次数、墙钟、单实验时间、科学计算 CPU 秒及可选 API 美元费用。Dummy/LR 各计一次实验，候选各计一次，最终测试评估也计一次；数据准备消耗 CPU/墙钟，不计训练实验数。最好为 Demo 保留至少 5 次实验额度。硬预算优先于最少实验目标；额度不足会交付已有结果而不补跑。

CPU 通过进程计时和 watchdog 监测，科学库限制单线程；墙钟到期终止子进程。终止调度存在系统粒度开销，报告保留实际测量值；结果不明时保留预留 CPU/Token，不虚构零消耗。进程启动、模型训练、统计审查纳入科学计算计量；报告写盘和调度收尾允许预算耗尽后执行。

## 真实云端规划 + 本地轻量决策

复用本地 `models.toml`，密钥可放 `cloud.api_key` 或对应环境变量，该文件不进入 Git。无需将密钥写入任务 YAML。科学研究使用内置结构化契约，根工作台的空 Prompt 槽不阻止科学研究模式；可在研究角色实现中调整指令。

确认 `[cloud]` 与 `[local]` 端点已启用，模型 ID 来自供应商/本机配置。云端从带有实验方法和证伪条件的候选假设卡片中选出研究路线，输出卡片 ID 与计划说明；建议云端 `max_output_tokens = 512`、`timeout_seconds = 60`，本地选择 `max_output_tokens = 256`。保持供应商所需的 `output_limit_field`、`json_output`、`disable_thinking` 设置。

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\deploy-research.ps1 -SkipInstall -Llm api -TaskConfig configs/api.example.yaml
```

模型先依据目标、训练画像与真实基线选择、排序可执行假设；每张卡片绑定确定的白名单实验模板，工程角色将其转成校验后的 ExperimentSpec。后续本地模型只接收相关审查摘要与剩余候选。连续两轮无支持证据可申请云端诊断。此版本不支持自由生成任意算法/特征代码，也不将模型随意生成的自然语言命题冒充已经实验验证的命题。API 失败时默认交付已有成果；只有 `llm.allow_mock: true` 才允许规划失败后转 Mock，并在报告标识。轻量选择失败时可用已有假设的确定性调度，不伪造模型成功。

API 模式任一适用的全局预算耗尽后，不再启动其他收费请求或科学计算，只导出已有结果（包括可能跳过最终测试）；Mock 模式的零模型调用额度不影响本地实验。建议为有模型参与的任务保留至少 4 次调用额度，而不是让规划恰好耗尽最后一次请求。

实际 `prompt_tokens` / `completion_tokens` 分开对账；缺失时保留 UTF-8 字节上界加协议开销的预留并标记未知。可在 `[cloud]` 配置 `input_price_per_million` 和 `output_price_per_million`（美元），按供应商适用价格自行填写；这是配置价格计算值，不是发票。无价格则费用未知；如果同时要求美元硬上限，拒绝不可定价的云调用。

云端请求默认跟随系统代理（本地回环请求不走代理）。系统代理不可用而云端可直连时，可在运行前设置 `NO_PROXY="*"` 绕过；代理正常时无需处理。

## 恢复、停止与复现

```powershell
.\.venv\Scripts\python.exe -m lazyresearch.science resume --run-dir runs/<RUN_ID>
.\.venv\Scripts\python.exe -m lazyresearch.science stop --run-dir runs/<RUN_ID>
.\.venv\Scripts\python.exe -m lazyresearch.science reproduce --run-dir runs/<RUN_ID>
```

SQLite checkpoint 恢复节点，Registry 复用完成记录；同一运行目录加排他锁。中断时结果不明的计算不会自动重跑，保留失败与预算预留。总墙钟从首次运行开始，离线等待也消耗墙钟；预算已耗尽的恢复只收尾。

测试权限在读取封存测试前持久化消费，崩溃后不会重复打开测试来“修复”结果。复现创建独立目录，在相同数据指纹、划分、种子和实验配置下重放；不重请求模型。查看 `reproduction_comparison.json`，数值环境变化可能产生合理差异。只加载本机可信产物中的 Joblib 模型，不使用第三方不可信模型文件。

## 产物与解释

`runs/<RUN_ID>/` 包含 `run_manifest.json`、`config.resolved.yaml`、`dataset_profile.json`、`baseline_metrics.json`、`hypotheses.jsonl`、`experiments.jsonl`、`reviews.jsonl`、`decision_trace.jsonl`、`model_calls.jsonl`、`budget.json`、`report.md`；有有效模型时导出 `best_model.joblib`，合法最终测试完成时导出 `predictions_test.csv` 与 `test_metrics.json`。保留 `registry.sqlite`、`checkpoints.sqlite` 和中间模型用于审计/恢复，目录可能含用户数据，不提交 Git。

报告区分验证集探索与封存测试。AP 使用 scikit-learn Average Precision，不能与梯形 PR-AUC 混用。配对 Bootstrap 的调整区间不消除自适应选择偏差；最终测试仅检查冻结模型泛化，不能据此声称超过未在测试集评估的基线。相关性不是因果增量，没有稳定提升也是合法结论。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

包含真实训练、禁用字段与训练预处理隔离、预算拒绝、未知用量、失败/超时、恢复复用、最终测试只消费一次、报告来源以及 HTTP 模拟。Windows 受限沙箱可能阻止回环 HTTP 或异步 I/O 初始化；在允许本机回环连接的终端执行完整测试。真实 API 冒烟单独记录（见 [终验收报告第 6 节](P0_ACCEPTANCE_REPORT.md)），不进入无密钥 CI。
