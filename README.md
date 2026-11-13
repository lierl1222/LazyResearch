# LazyResearch

本地研究工作台。LangGraph 编排规划、证据收集、假设、执行、验证与修正。当前提供确定性测试适配器，用于验证闭环行为和预算控制。

## 启动

需要 CPython 3.11+ 和 Node.js 20.19+（或 22.12+）。以下命令在项目根目录运行。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run build
.\.venv\Scripts\python -m uvicorn lazyresearch.api:create_app --factory
```

打开 [本地工作台](http://127.0.0.1:8000)，点击「启动研究」。测试流程在首轮并行执行两个候选，其中一个模拟失败，第二轮依据首轮证据修正并通过验证。刷新页面会按 URL 中的运行 ID 回放事件。

## CLI 与测试

```powershell
.\.venv\Scripts\python -m lazyresearch --goal "验证研究闭环" --output .lazyresearch\report.zip
.\.venv\Scripts\python -m lazyresearch --task task.json
.\.venv\Scripts\python -m lazyresearch --resume <run-id>
.\.venv\Scripts\python -m unittest discover -s tests -v
```

第二条命令读取研究包解压后的 `task.json`。运行记录和检查点默认保存在 `.lazyresearch/`。Web 可用 `LAZYRESEARCH_DIR` 指定目录，CLI 可用 `--state-dir`。首版按本地单进程运行，同一状态目录由一个服务实例管理。

## 接入

- 在 `lazyresearch/adapters.py` 查看 `ResearchAdapter` 契约。通过 `Runner(adapters=...)` 注册实现，由适配器定义工具、指标和验证标准。工具应尊重传入的时限并用 operation ID 对外部副作用做幂等处理。运行器在时限到达时停止等待，Python 无法强制终止正在运行的任意线程。
- 在 `lazyresearch/model_gateway.py` 查看 `ModelGateway` 和 `Prompts`。规划、诊断槽默认为空，默认云请求和 token 上限均为 0。接入供应商时，通过 `Runner` 注入网关和 Prompt，由网关给出保守 token 上界、限制输出并提供实际用量。将同一 `Runner` 传给 `create_app(runner=...)` 即可供 Web 使用。
- `POST /runs` 启动任务，`GET /runs/{id}` 返回快照，`GET /runs/{id}/events` 用 SSE 返回事件并支持 `Last-Event-ID`，`GET /runs/{id}/artifacts` 下载研究包。

## 编排参考

参考 [agentic-rag-for-dummies @ c1b339b](https://github.com/GiovanniPasq/agentic-rag-for-dummies/tree/c1b339b54f0927bd0b469fcce70f3cd5de4e918d/project/rag_agent) 的主图和子图分工、条件边与 `Send` 聚合。参考源码通过独立的稀疏检出对照。LazyResearch 用结构化证据连接阶段，并使用本地报告节点在预算耗尽时收尾。


## 有机毛玻璃工作台

打开首页直接进入研究工作台。在左侧输入目标、选择适配器并编辑预算，点击「启动研究」执行真实 API。带 `?run=<id>` 的链接支持刷新回放。中央提供按轮次折叠的流程记录与原始执行详情，右侧显示真实资源用量和研究包下载入口。

- `web/src/glass.css`：颜色、玻璃透明度、模糊、阴影、无模糊降级及低动态样式。
- `web/src/style.css`：布局、字体和响应式。
- `web/src/components/Glass.jsx`：GlassCard / GlassInput / GlassButton 与原创银色 SVG 背景。
- `web/src/components/ResearchProgress.jsx`：真实轮次状态、修正反馈弧线、资源指标及零预算处理。

前端修改后运行 `npm --prefix web run build`，再使用上面的 Uvicorn 命令预览。项目未配置独立 lint 或 TypeScript 类型检查脚本。默认研究适配器仍为确定性测试适配器。
