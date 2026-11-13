import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

const phases = [
  ['plan', '规划'], ['evidence', '收集证据'], ['hypothesis', '提出假设'],
  ['execution', '执行'], ['validation', '验证'], ['revision', '修正'],
]
const stageLabels = {
  ...Object.fromEntries(phases), queued: '已排队', running: '开始研究',
  results: '执行结果', finished: '运行结束', cloud_skipped: '跳过云调用',
  cloud_reserved: '预留云额度', cloud_accounted: '云用量入账', cloud_failed: '云请求失败',
  local_accounted: '小模型用量入账', local_failed: '小模型请求失败',
  local_choice: '小模型选择优先候选',
}
const reasons = {
  validated: '验证通过', tool_budget: '工具额度已用尽', time_budget: '达到时间上限',
  round_budget: '达到轮数上限', no_candidates: '没有可执行的候选', execution_error: '运行出错',
  budget: '额度不足', model_or_prompt_unconfigured: '模型或 Prompt 尚未配置',
  estimate_unavailable: '无法估算请求用量',
  plan_unavailable: '云端计划不可用，使用本地计划',
}
const limits = [
  ['rounds', '轮数', 3, 1, 100], ['tools', '工具次数', 6, 0, 200],
  ['seconds', '时间（秒）', 120, 1, 86400], ['cloud_requests', '云请求', 0, 0, 100],
  ['tokens', '总 token', 0, 0, undefined],
]
const initial = Object.fromEntries(limits.map(([key, , value]) => [key, value]))

async function getJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    const detail = Array.isArray(error.detail) ? error.detail.map(item => item.msg).join('，') : error.detail
    throw new Error(detail || `请求失败（${response.status}）`)
  }
  return response.json()
}

function EventDetails({ event }) {
  const narrative = event.summary || event.validation?.summary || event.revision?.summary
  return <>
    {narrative && <p>{narrative}</p>}
    {event.source && <p className="refs">{event.source === 'cloud' ? '云端研究计划' : '适配器计划'}</p>}
    {event.steps?.length > 0 && <ol>{event.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}
    {event.candidate_id && <p><code>{event.candidate_id}</code></p>}
    {event.revision && <p className="refs">依据 {event.revision.evidence_ids.join(' · ')}</p>}
    {event.candidates?.map(candidate => (
      <p key={candidate.id}>{candidate.hypothesis}<br />
        <span className="refs">{candidate.id} · {candidate.evidence_ids.join(' · ')}</span></p>
    ))}
    {event.evidence?.map(item => <p key={item.id}><code>{item.id}</code> {item.summary}</p>)}
    {event.results?.map(result => (
      <p key={result.candidate_id}>
        <span className={result.error ? 'negative' : 'positive'}>{result.summary}</span>
        {' · '}{result.candidate_id}{result.error && <><br />{result.error}</>}
      </p>
    ))}
    {event.reason && <p>{reasons[event.reason] || event.reason}</p>}
    {event.stop_reason && <p>{reasons[event.stop_reason] || event.stop_reason}</p>}
  </>
}

function App() {
  const [config, setConfig] = useState(null)
  const [runId, setRunId] = useState(() => new URLSearchParams(location.search).get('run'))
  const [goal, setGoal] = useState('验证研究流程能否依据首轮结果自动修正')
  const [resources, setResources] = useState('')
  const [adapter, setAdapter] = useState('fixture')
  const [budget, setBudget] = useState(initial)
  const [events, setEvents] = useState([])
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(true)
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    getJson('/config').then(data => {
      setConfig(data)
      if (!new URLSearchParams(location.search).has('run')) setAdapter(data.adapters[0] || '')
    }).catch(err => setError(err.message))
  }, [])

  useEffect(() => {
    if (!runId) return
    const base = `/runs/${encodeURIComponent(runId)}`
    let active = true
    let stream
    let interval
    const sync = async () => {
      const data = await getJson(base)
      if (active) {
        setSnapshot(data)
        setSeconds(data.elapsed)
      }
      return data
    }
    sync().then(data => {
      if (!active) return
      setGoal(data.task.goal)
      setResources(data.task.resources.join('\n'))
      setAdapter(data.task.adapter_id)
      setBudget(data.task.budget)
      if (['queued', 'running'].includes(data.status)) {
        interval = setInterval(() => sync().catch(() => {}), 1000)
      }
      stream = new EventSource(`${base}/events`)
      stream.onopen = () => setConnected(true)
      stream.onerror = () => setConnected(false)
      stream.onmessage = message => {
        const event = JSON.parse(message.data)
        setEvents(prior => prior.some(item => item.id === event.id) ? prior : [...prior, event])
        if (['finished', 'failed'].includes(event.status)) {
          stream.close()
          clearInterval(interval)
          sync().catch(err => { if (active) setError(err.message) })
        }
      }
    }).catch(err => { if (active) setError(err.message) })
    return () => {
      active = false
      stream?.close()
      clearInterval(interval)
    }
  }, [runId])

  async function start(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const task = {goal, adapter_id: adapter, resources: resources.split('\n').map(s => s.trim()).filter(Boolean), budget}
      const { id } = await getJson('/runs', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(task),
      })
      history.replaceState(null, '', `?run=${id}`)
      setEvents([])
      setSnapshot(null)
      setSeconds(0)
      setConnected(true)
      setRunId(id)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const terminal = ['finished', 'failed'].includes(snapshot?.status)
  const lastPhase = events.findLast(item => phases.some(([key]) => key === item.stage))?.stage
  const accounting = events.findLast(event => event.cloud_requests !== undefined) || {}
  const localUsage = events.findLast(event => event.local_requests !== undefined) || {}
  const toolUse = events.findLast(event => event.tools !== undefined)?.tools ?? snapshot?.tools ?? 0
  const status = snapshot?.stop_reason ? (reasons[snapshot.stop_reason] || snapshot.stop_reason)
    : runId ? (connected ? '研究运行中' : '正在重连') : '等待启动'
  const activeBudget = snapshot?.task.budget || budget

  return <>
    <header>
      <div className="brand"><span className="mark" aria-hidden="true">↗</span>LazyResearch</div>
      <span className="mode"><i />{[
        config?.models?.local?.ready && '本地小模型已配置',
        config?.models?.cloud?.ready && '云模型已配置',
      ].filter(Boolean).join(' · ') || '本地规则模式'}</span>
    </header>
    <main>
      <div className="title">
        <div><h1>研究工作台</h1><p>查看假设、实验结果与每轮修正依据。</p></div>
        {runId && <code className="run-id" title={runId}>{runId.slice(0, 10)}</code>}
      </div>
      <div className="layout">
        <aside className="panel">
          <h2>研究任务</h2>
          <form onSubmit={start}>
            <label>研究目标<textarea required maxLength={2000} rows={3} value={goal} onChange={e => setGoal(e.target.value)} /></label>
            <label>执行适配器<select value={adapter} onChange={e => setAdapter(e.target.value)}>
              {(config?.adapters || ['fixture']).map(id => <option key={id} value={id}>{id === 'fixture' ? '确定性测试适配器' : id}</option>)}
            </select></label>
            <label>输入资源 <span className="optional">可选</span><textarea rows={2} placeholder="每行一个资源引用" value={resources} onChange={e => setResources(e.target.value)} /></label>
            <fieldset><legend>运行预算</legend><div className="limits">
              {limits.map(([key, name, , min, max]) => <label key={key}>{name}
                <input required type="number" min={min} max={max} value={budget[key]}
                  onChange={e => setBudget({...budget, [key]: e.target.value === '' ? '' : Number(e.target.value)})} />
              </label>)}
            </div></fieldset>
            <button disabled={busy || !config || (!!runId && !terminal && !error)}>{busy ? '正在启动…' : '启动研究'} <span aria-hidden="true">→</span></button>
            {error && <p className="negative" role="alert">{error}</p>}
          </form>
        </aside>
        <section className="panel workspace" aria-labelledby="progress">
          <div className="section-head"><h2 id="progress">研究进度</h2><span role="status" className="status">{status}</span></div>
          <ol className="phases" aria-label="研究阶段">
            {phases.map(([key, label]) => <li key={key} className={key === lastPhase ? 'current' : ''}>
              {label}
            </li>)}
          </ol>
          {snapshot?.error && <p className="negative" role="alert">{snapshot.error}</p>}
          {events.length ? <div className="timeline">
            {[...events].reverse().map(event => <article key={event.id}>
              <div className="event-head"><h3>{stageLabels[event.stage] || event.stage}</h3>
                {event.round > 0 && <span>第 {event.round} 轮</span>}</div>
              <EventDetails event={event} />
            </article>)}
          </div> : <div className="empty"><span aria-hidden="true">↳</span><p>运行事件将在这里显示</p></div>}
        </section>
        <aside className="panel metrics">
          <h2>资源用量</h2>
          <dl>
            <div><dt>运行时间</dt><dd>{seconds.toFixed(2)} <small>/ {activeBudget.seconds} 秒</small></dd></div>
            <div><dt>工具调用</dt><dd>{toolUse} <small>/ {activeBudget.tools}</small></dd></div>
            <div><dt>云请求</dt><dd>{accounting.cloud_requests ?? snapshot?.cloud_requests ?? 0} <small>/ {activeBudget.cloud_requests}</small></dd></div>
            <div><dt>已确认 token</dt><dd>{accounting.tokens ?? snapshot?.tokens ?? 0} <small>/ {activeBudget.tokens}</small></dd></div>
            <div><dt>待确认 token</dt><dd>{accounting.tokens_pending ?? snapshot?.tokens_pending ?? 0}</dd></div>
            {(config?.models?.local?.ready || localUsage.local_requests || snapshot?.local_requests) ? <>
              <div><dt>小模型请求</dt><dd>{localUsage.local_requests ?? snapshot?.local_requests ?? 0}</dd></div>
              <div><dt>小模型已确认 token</dt><dd>{localUsage.local_tokens ?? snapshot?.local_tokens ?? 0}</dd></div>
            </> : null}
          </dl>
          {terminal && <a className="download" href={`/runs/${encodeURIComponent(runId)}/artifacts`}>下载研究包 <span aria-hidden="true">↓</span></a>}
        </aside>
      </div>
    </main>
  </>
}

createRoot(document.getElementById('root')).render(<App />)
