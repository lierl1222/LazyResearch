import React, { useState } from 'react'

export function ResourceMetric({ label, value, limit, unit = '' }) {
  const enabled = Number(limit) > 0
  const percent = enabled ? value / limit * 100 : 0
  return <div className={percent > 100 ? 'metric-over' : ''}>
    <dt>{label}</dt>
    <dd>{value} {limit !== undefined && <small>/ {limit} {unit}</small>}</dd>
    {enabled && <progress aria-label={`${label}使用率`} max={100} value={Math.min(100, percent)} />}
    {limit !== undefined && !enabled && <span className="metric-disabled">未启用</span>}
    {percent > 100 && <span className="negative">已超预算 {Math.round(percent - 100)}%</span>}
  </div>
}

function stepSummary(event) {
  if (event.validation) return event.validation.summary
  if (event.revision) return event.revision.summary
  if (event.results) {
    const failures = event.results.filter(result => result.error).length
    return `${event.results.length} 项结果，${failures} 项失败`
  }
  if (event.summary) return event.summary
  if (event.candidates) return event.candidates.map(candidate => candidate.hypothesis).join('；')
  if (event.evidence) return `已收集 ${event.evidence.length} 条证据`
  if (event.candidate_ids) return `执行 ${event.candidate_ids.length} 个候选方案`
  return ''
}

function phaseState(key, items, events, live, last) {
  if (key === 'execution' && items.some(e => e.results?.some(r => r.error))) return ['node-error', '部分执行失败']
  if (key === 'validation' && items.some(e => e.validation?.passed === false)) return ['node-warning', '验证未通过']
  if (key === 'revision' && items.some(e => e.revision)) return ['node-warning', '已修正']
  if (items.some(e => e.stage === key)) {
    return live && last === key ? ['current', '执行中'] : ['visited', '已记录']
  }
  if (['plan', 'evidence'].includes(key) && events.some(e => !e.round && e.stage === key)) return ['inherited', '沿用研究准备']
  return ['', live ? '待执行' : '未执行']
}

function RoundRecord({ number, items, labels, EventDetails }) {
  const outcome = items.findLast(e => e.revision || e.validation)
  const steps = items.filter(e => stepSummary(e))
  return <details className="round-record">
    <summary><strong>{number ? `第 ${number} 轮` : '研究准备'}</strong>
      <span>{outcome ? stepSummary(outcome) : steps.length ? stepSummary(steps.at(-1)) : `${items.length} 条记录`}</span>
    </summary>
    {steps.map(event => <details className="step-record" key={event.id}>
      <summary><strong>{labels[event.stage] || event.stage}</strong><span>{stepSummary(event)}</span></summary>
      <EventDetails event={event} />
      {event.candidate_ids && <p>候选方案　<code>{event.candidate_ids.join(' · ')}</code></p>}
    </details>)}
  </details>
}

export function ResearchProgress({ events, terminal, failed, phases, labels, EventDetails }) {
  const [tab, setTab] = useState('flow')
  const [selected, setSelected] = useState(null)
  const rounds = [...new Set(events.map(e => e.round || 0))].sort((a, b) => b - a)
  const latest = rounds[0] || 0
  const round = selected ?? latest
  const items = events.filter(e => (e.round || 0) === round)
  const last = items.findLast(e => phases.some(([key]) => key === e.stage))?.stage
  const validation = events.findLast(e => e.validation)
  const revision = events.findLast(e => e.revision)
  const live = !terminal && round === latest
  const tabs = [['flow', '轮次记录'], ['logs', '执行日志']]
  return <>
    {terminal && validation && <section className="finding">
      <h3>{validation.round === latest && !failed ? '验证结论' : '最近一次验证'} <small>第 {validation.round} 轮</small></h3>
      <p>{validation.validation.summary}</p>
      {revision && <div className="revision-note"><strong>第 {revision.round} 轮修正</strong>
        <p>{revision.revision.summary}</p>
        <details><summary>查看修正依据（{revision.revision.evidence_ids.length}）</summary>
          <ul>{revision.revision.evidence_ids.map(id => {
            const evidence = events.flatMap(e => e.evidence || []).find(item => item.id === id)
            return <li key={id}>{evidence?.summary} <code>{id}</code></li>
          })}</ul>
        </details>
      </div>}
    </section>}
    {Boolean(rounds.length) && <label className="round-select">查看阶段
      <select value={round} onChange={e => setSelected(Number(e.target.value))}>
        {rounds.map(n => <option key={n} value={n}>{n ? `第 ${n} 轮` : '研究准备'}</option>)}
      </select>
    </label>}
    <div className="flow-network"><ol className="phases" aria-label="研究阶段">{phases.map(([key, label]) => {
      const [style, state] = phaseState(key, items, events, live, last)
      return <li key={key} className={style} title={state}><span className="node" aria-hidden="true" /><span>{label}</span><span className="sr-only">{state}</span></li>
    })}</ol></div>
    {!events.length ? <p className="idle-help">填写研究目标并启动任务后，可以在这里查看每轮的假设、验证结果和修正依据。</p> : <>
      <div className="view-tabs" role="tablist" aria-label="研究记录视图">{tabs.map(([id, name]) =>
        <button key={id} id={`tab-${id}`} role="tab" aria-controls="research-records" aria-selected={tab === id}
          onClick={() => setTab(id)} onKeyDown={e => {
            if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return
            e.preventDefault()
            const next = id === 'flow' ? 'logs' : 'flow'
            setTab(next)
            document.getElementById(`tab-${next}`)?.focus()
          }}>{name}</button>)}</div>
      <div id="research-records" role="tabpanel" aria-labelledby={`tab-${tab}`} className="timeline">
        {tab === 'flow' ? rounds.map(n => <RoundRecord key={n} number={n}
          items={events.filter(e => (e.round || 0) === n)} labels={labels} EventDetails={EventDetails} />)
          : events.map(event => <details className="log-entry" key={event.id}>
            <summary><span>{labels[event.stage] || event.stage}</span><small>{event.round ? `第 ${event.round} 轮` : '研究准备'} · <code>#{event.id}</code></small></summary>
            <EventDetails event={event} /><pre>{JSON.stringify(event, null, 2)}</pre>
          </details>)}
      </div>
    </>}
  </>
}
