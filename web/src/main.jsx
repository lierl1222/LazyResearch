import React, { useEffect, useState, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import './glass.css'
import { GlassCard, GlassInput, GlassButton, OrganicBackground } from './components/Glass'
import { ResearchProgress, ResourceMetric } from './components/ResearchProgress'

const phases = [
  ['plan', '规划'], ['evidence', '收集证据'], ['hypothesis', '提出假设'],
  ['execution', '执行'], ['validation', '验证'], ['revision', '修正'],
]
const stageLabels = {
  ...Object.fromEntries(phases), queued: '已排队', running: '开始研究',
  results: '执行结果', finished: '运行结束', cloud_skipped: '跳过云调用',
  cloud_reserved: '预留云额度', cloud_accounted: '云用量入账', cloud_failed: '云请求失败',
}
const reasons = {
  validated: '验证通过', tool_budget: '工具额度已用尽', time_budget: '达到时间上限',
  round_budget: '达到轮数上限', no_candidates: '没有可执行的候选', execution_error: '运行出错',
  budget: '额度不足', model_or_prompt_unconfigured: '模型或 Prompt 尚未配置',
  estimate_unavailable: '无法估算请求用量',
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
  const [goal, setGoal] = useState('')
  const submissionLock = useRef(false)
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
    if (submissionLock.current || !goal.trim()) return
    submissionLock.current = true
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
      submissionLock.current = false
    }
  }

  const terminal = ['finished', 'failed'].includes(snapshot?.status)
  const accounting = events.findLast(event => event.cloud_requests !== undefined) || {}
  const toolUse = events.findLast(event => event.tools !== undefined)?.tools ?? snapshot?.tools ?? 0
  const status = snapshot?.stop_reason ? (reasons[snapshot.stop_reason] || snapshot.stop_reason)
    : runId ? (connected ? '研究运行中' : '正在重连') : '等待启动'
  const activeBudget = snapshot?.task.budget || budget

  const failed = snapshot?.status === 'failed'
  const statusTone = failed ? 'failure' : snapshot?.stop_reason === 'validated' ? 'success' : terminal || events.at(-1)?.stage === 'revision' ? 'warning' : runId ? 'active' : 'idle'
  return <div className="dashboard">
    <OrganicBackground />
    <header>
      <div className="page-heading"><h1>研究工作台</h1><span className="mode"><i />{config?.mode === 'gateway_ready' ? '云网关可用' : '本地执行模式'}</span></div>
      {runId && <code className="run-id" title={runId}>Session {runId.slice(0, 10).toUpperCase()}</code>}
    </header>
    <main>
      <div className="layout">
        <GlassCard as="aside" className="task-panel">
          <h2>研究任务</h2>
          <form onSubmit={start}>
            <label>研究目标<GlassInput as="textarea" placeholder="输入需要研究或验证的问题" required maxLength={2000} rows={3} value={goal} onChange={e => setGoal(e.target.value)} /></label>
            <label>执行适配器<GlassInput as="select" value={adapter} onChange={e => setAdapter(e.target.value)}>
              {(config?.adapters || ['fixture']).map(id => <option key={id} value={id}>{id === 'fixture' ? '确定性测试适配器' : id}</option>)}
            </GlassInput></label>
            <label>输入资源 <span className="optional">可选</span><GlassInput as="textarea" rows={2} placeholder="每行一个资源引用" value={resources} onChange={e => setResources(e.target.value)} /></label>
            <details className="budget-settings"><summary>运行预算</summary><fieldset aria-label="运行预算"><div className="limits">
              {limits.map(([key, name, , min, max]) => <label key={key}>{name}
                <GlassInput required type="number" min={min} max={max} value={budget[key]}
                  onChange={e => setBudget({...budget, [key]: e.target.value === '' ? '' : Number(e.target.value)})} />
              </label>)}
            </div></fieldset></details>
            <GlassButton disabled={busy || !config || (!!runId && !terminal && !error)}>{busy ? '正在启动…' : '启动研究'} <span aria-hidden="true">→</span></GlassButton>
            {error && <p className="negative" role="alert">{error}</p>}
          </form>
        </GlassCard>
        <GlassCard as="section" className="workspace" aria-labelledby="progress">
          <div className="section-head"><h2 id="progress">研究进度</h2><span role="status" className={`status ${statusTone}`}>{failed ? '执行失败' : status}</span></div>
          {snapshot?.task.goal && <p className="run-goal">{snapshot.task.goal}</p>}
          {snapshot?.error && <p className="negative" role="alert">{snapshot.error}</p>}
          <ResearchProgress key={runId || 'draft'} events={events} terminal={terminal} failed={failed} phases={phases} labels={stageLabels} EventDetails={EventDetails} />
        </GlassCard>
        <GlassCard as="aside" className="metrics">
          <h2>资源用量</h2>
          <dl className="resource-list">
            <ResourceMetric label="运行时间" value={Number(seconds || 0).toFixed(2)} limit={activeBudget.seconds} unit="秒" />
            <ResourceMetric label="工具调用" value={toolUse} limit={activeBudget.tools} />
            <ResourceMetric label="云请求" value={accounting.cloud_requests ?? snapshot?.cloud_requests ?? 0} limit={activeBudget.cloud_requests} />
            <ResourceMetric label="已确认 token" value={accounting.tokens ?? snapshot?.tokens ?? 0} limit={activeBudget.tokens} />
            <ResourceMetric label="待确认 token" value={accounting.tokens_pending ?? snapshot?.tokens_pending ?? 0} />
          </dl>
          {terminal && <GlassButton as="a" className="download" href={`/runs/${encodeURIComponent(runId)}/artifacts`}>下载研究包 <span aria-hidden="true">↓</span></GlassButton>}
        </GlassCard>
      </div>
    </main>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
