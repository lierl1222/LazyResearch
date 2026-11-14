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

function ResearchBot() {
  return <svg className="research-bot" viewBox="0 0 180 180" fill="none" aria-hidden="true">
    <ellipse cx="90" cy="158" rx="43" ry="8" fill="currentColor" opacity=".08" />
    <path d="M90 35V23" stroke="currentColor" strokeWidth="3"/><circle cx="90" cy="19" r="5" fill="#F6D782"/>
    <rect x="57" y="39" width="66" height="52" rx="21" fill="white" stroke="currentColor" strokeWidth="3"/>
    <rect x="67" y="51" width="46" height="25" rx="10" fill="#F1EDFF" stroke="currentColor" strokeWidth="2"/>
    <path d="M77 62h5m16 0h5m-18 7q5 4 10 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
    <rect x="61" y="96" width="58" height="44" rx="15" fill="white" stroke="currentColor" strokeWidth="3"/>
    <path d="M61 111C39 115 42 91 32 88m87 23c22 4 19-20 29-23M79 141v12m22-12v12" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
    <rect x="22" y="77" width="18" height="18" rx="5" fill="#D8F7EA" stroke="#70C6A4" strokeWidth="2" transform="rotate(-15 31 86)"/>
    <rect x="140" y="77" width="18" height="18" rx="5" fill="#FFF1C7" stroke="#E9CB75" strokeWidth="2" transform="rotate(15 149 86)"/>
    <path d="M78 113h24m-24 9h15" stroke="#DBD2F7" strokeWidth="3" strokeLinecap="round"/>
  </svg>
}

function ResearchTree({ events, selectedPhase, onSelect, terminal, round }) {
  const active = events.findLast(event => phases.some(([key]) => key === event.stage))?.stage
  const reached = new Set(events.map(event => event.stage))
  const points = [[65,299],[235,249],[60,202],[235,155],[71,108],[218,61]]
  const activeIndex = phases.findIndex(([key]) => key === active)
  const top = activeIndex >= 0 ? points[activeIndex][1] : 347
  return <div className="tree-wrap">
    <svg className="growth-tree" viewBox="0 0 300 392" role="group" aria-label="研究生长树">
      <defs><linearGradient id="tree-gold" x1="0" y1="1" x2="0" y2="0"><stop stopColor="#e9b638"/><stop offset="1" stopColor="#f6d77c"/></linearGradient></defs>
      <ellipse cx="150" cy="357" rx="68" ry="12" fill="#f4ecd8"/><ellipse cx="150" cy="357" rx="43" ry="6" fill="#e7d6ac" opacity=".45"/>
      <circle cx="154" cy="165" r="112" fill="#fff8e5" opacity=".55"/>
      <circle cx="54" cy="67" r="3" fill="#e7c367" opacity=".5"/><circle cx="259" cy="109" r="2" fill="#d9b555" opacity=".5"/><circle cx="39" cy="256" r="2" fill="#e7c367" opacity=".6"/>
      <path d="M150 348 C143 302 167 276 152 235 S140 170 152 132 S162 71 151 35" fill="none" stroke="#ede5d1" strokeWidth="9" strokeLinecap="round"/>
      <path d="M128 362q22-23 44 0m-22-12v17" fill="none" stroke="#ddc78e" strokeWidth="2" strokeLinecap="round"/>
      
      <clipPath id="tree-growth-clip"><rect x="0" y={top-28} width="300" height={392-top+28}/></clipPath>
      <path className="grown-trunk" clipPath="url(#tree-growth-clip)" d="M150 348 C143 302 167 276 152 235 S140 170 152 132 S162 71 151 35" fill="none" stroke="url(#tree-gold)" strokeWidth="7" strokeLinecap="round"/>
      <path d="M151 42 Q130 25 138 14 Q159 19 151 42" fill={reached.size ? '#e7bd54' : '#e8dfc9'}/>
      <path d="M155 59 Q174 37 183 43 Q179 63 155 59" fill={reached.size > 4 ? '#d8b14c' : '#ebe3d1'}/>
      {phases.map(([key,label],i) => {
        const [x,y] = points[i], done = reached.has(key), current = active === key
        const branch = `M152 ${y+32} C${i%2===0 ? 113 : 189} ${y+28} ${i%2===0 ? 113 : 187} ${y-6} ${x} ${y}`
        return <g key={key} className={'tree-node ' + (done ? 'grown ' : '') + (current ? 'growing ' : '') + (selectedPhase === key ? 'chosen' : '')} role="button" tabIndex={0} aria-label={'查看'+label+'详情'} aria-pressed={selectedPhase===key} onClick={()=>onSelect(key)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(key)}}}>
          <title>{label}{current ? ' · 当前阶段' : done ? ' · 已有记录' : ' · 等待推进'}</title>
          <path className="tree-branch" d={branch} fill="none" strokeWidth="2"/>
          <path className="tree-leaf" d={i%2===0 ? `M126 ${y+21}q-30-2-28-22q23-3 28 22` : `M177 ${y+21}q30-2 28-22q-23-3-28 22`} />
          <path className="tree-leaf leaf-secondary" d={i%2===0 ? `M137 ${y+29}q-4-24 10-29q12 17-10 29` : `M166 ${y+29}q4-24-10-29q-12 17 10 29`} />
          {current && <rect className={'node-halo ' + (!terminal ? 'breathe' : '')} x={x-51} y={y-21} width="102" height="42" rx="15"/>}
          <rect className="node-card" x={x-46} y={y-16} width="92" height="32" rx="11"/>
          <circle className="node-dot" cx={x-31} cy={y} r="3"/>
          <text x={x+3} y={y+4} textAnchor="middle">{label}</text>
          {current && <text className="node-current" x={x} y={y+32} textAnchor="middle">{terminal ? '最近阶段' : '正在推进'}</text>}
        </g>
      })}
      <circle cx="150" cy="348" r="8" fill={events.length ? '#e7b638' : '#ddd6c4'}/>
      <circle cx="150" cy="348" r="3" fill="white"/>
      <text className="tree-root-label" x="150" y="386" textAnchor="middle">{events.length ? `第 ${round || 1} 轮研究` : '等待种下一个问题'}</text>
    </svg>
    <div className="tree-caption"><span className={events.length ? 'tree-status-dot' : ''}/>{active ? Object.fromEntries(phases)[active] + (terminal ? ' · 本轮已结束' : ' · 正在进行') : '研究尚未开始'}</div>
  </div>
}

function App() {
  const [selectedPhase, changePhase] = useState(null)
  const [phaseTabs, setPhaseTabs] = useState([])
  const [phaseQuestions, setPhaseQuestions] = useState({})
  const [phaseChats, setPhaseChats] = useState({})
  function setSelectedPhase(key) { changePhase(key); if(key) setPhaseTabs(tabs => tabs.includes(key) ? tabs : [...tabs,key]) }
  function askPhase(e) {
    e.preventDefault()
    const question = (phaseQuestions[selectedPhase] || '').trim()
    if (!question) return
    const records = events.filter(item => item.stage === selectedPhase || (selectedPhase === 'execution' && item.stage === 'results'))
    const facts = records.map(item => ({round:item.round, summary:item.summary, evidence:item.evidence, candidates:item.candidates, results:item.results, validation:item.validation, revision:item.revision})).map(item => JSON.stringify(item, null, 2)).join('\n')
    const answer = records.length ? '当前为记录查询，以下是本步骤的原始记录，供核对：\n' + facts : '本步骤暂无运行记录。当前未接入对话模型，无法进行开放式回答。'
    setPhaseChats(chats => ({...chats,[selectedPhase]:[...(chats[selectedPhase] || []),{question,answer}]}))
    setPhaseQuestions(values => ({...values,[selectedPhase]:''}))
  }
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
      setSelectedPhase(null)
      setPhaseTabs([])
      setPhaseChats({})
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
  const toolUse = events.findLast(event => event.tools !== undefined)?.tools ?? snapshot?.tools ?? 0
  const status = snapshot?.stop_reason ? (reasons[snapshot.stop_reason] || snapshot.stop_reason)
    : runId ? (connected ? '研究运行中' : '正在重连') : '等待启动'
  const activeBudget = snapshot?.task.budget || budget

  const running = busy || (!!runId && !terminal && !error)
  const usage = [
    ['运行时间', seconds.toFixed(1), activeBudget.seconds, '秒', seconds],
    ['工具调用', toolUse, activeBudget.tools, '次', toolUse],
    ['云端请求', accounting.cloud_requests ?? snapshot?.cloud_requests ?? 0, activeBudget.cloud_requests, '次', accounting.cloud_requests ?? snapshot?.cloud_requests ?? 0],
    ['Token', accounting.tokens ?? snapshot?.tokens ?? 0, activeBudget.tokens, '', accounting.tokens ?? snapshot?.tokens ?? 0],
  ]
  const phaseIndex = phases.findIndex(([key]) => key === lastPhase)

  return <>
    <header>
      <div className="brand"><span className="header-logo pixel-round-logo" role="img" aria-label="LazyResearch 圆形标志" /><span className="brand-name">LazyResearch</span><span className="pixel-leds" aria-hidden="true"><i/><i/><i/></span></div>
      <span className="mode"><i />{config?.mode === 'gateway_ready' ? '云网关可用' : '本地演示模式'}</span>
    </header>
    <main>
      <div className="layout">
        <aside className="panel settings">
          <div className="panel-heading"><h2><span className="pixel-icon icon-flask"/>研究空间</h2></div>
          <div className="settings-scroll">
            <div className="section-label">任务设置</div>
            <label>研究场景<select form="research-form" value={adapter} disabled={running} onChange={e => setAdapter(e.target.value)}>
              {(config?.adapters || ['fixture']).map(id => <option key={id} value={id}>{id === 'fixture' ? '研究闭环 · 演示' : id}</option>)}
            </select></label>
            <label>参考资源 <textarea disabled={running} rows={3} placeholder="每行输入一个资源引用" value={resources} onChange={e => setResources(e.target.value)} /></label>
            <fieldset disabled={running}><legend><span className="pixel-icon icon-coins"/>预算配置 </legend><div className="limits">
              {limits.map(([key, name, , min, max]) => <label key={key}>{name}
                <input form="research-form" required type="number" min={min} max={max} value={budget[key]}
                  onChange={e => setBudget({...budget, [key]: e.target.value === '' ? '' : Number(e.target.value)})} />
              </label>)}
            </div></fieldset>
            
          </div>
          <div className="sidebar-footer"><span className="connection-dot" />服务{config ? '已连接' : '连接中'}</div>
        </aside>
        <section className="panel conversation" aria-label="研究工作区">
          {phaseTabs.length > 0 && <nav className="phase-tabs" aria-label="研究标签页"><button className={!selectedPhase ? 'active' : ''} onClick={()=>changePhase(null)}>研究对话</button>{phaseTabs.map(key=><div className={'phase-tab ' + (selectedPhase===key?'active':'')} key={key}><button onClick={()=>changePhase(key)}>{Object.fromEntries(phases)[key]}</button><button aria-label={'关闭'+Object.fromEntries(phases)[key]} onClick={()=>{setPhaseTabs(tabs=>tabs.filter(t=>t!==key));if(selectedPhase===key)changePhase(null)}}>×</button></div>)}</nav>}
          
          {selectedPhase ? <div className="phase-detail">
            
            <div className="detail-banner"><span>{String(phases.findIndex(([key]) => key === selectedPhase) + 1).padStart(2, '0')}</span><div><h1>{Object.fromEntries(phases)[selectedPhase]}</h1></div></div>
            {events.filter(event => event.stage === selectedPhase || (selectedPhase === 'execution' && event.stage === 'results')).length ? events.filter(event => event.stage === selectedPhase || (selectedPhase === 'execution' && event.stage === 'results')).map(event => <article className="reply detail-record" key={event.id}><div className="event-head"><h3>{stageLabels[event.stage] || event.stage}</h3><span>{event.round > 0 ? `第 ${event.round} 轮` : '阶段记录'}</span></div><EventDetails event={event} /></article>) : <div className="detail-empty"><span>◎</span><h3>暂无阶段记录</h3><p>{runId ? '研究推进至此阶段后，记录将在这里显示。' : '启动研究后，可在这里查看对应阶段的详情。'}</p></div>}
            <div className="phase-chat-log">{(phaseChats[selectedPhase] || []).map((chat,index)=><div key={index}><p className="phase-question">{chat.question}</p><pre className="phase-answer">{chat.answer}</pre></div>)}</div>
          </div> : <><div className="messages" role="log" aria-label="研究对话记录">
            {!runId ? <div className="welcome"><div className="welcome-mascot coding-art" role="img" aria-label="LazyResearch 小人正在写代码" /><h1>你的下一个发现，从这里开始。</h1><div className="suggestions">{['验证研究流程能否依据首轮结果自动修正', '检查有限预算下的失败恢复流程'].map(text => <button type="button" key={text} onClick={() => setGoal(text)}>{text}<span>↗</span></button>)}</div></div> : <>
              <div className="user-message"><p>{snapshot?.task.goal || goal}</p></div>
              <div className="assistant-intro"><span className="avatar">✳</span><div><strong>LazyResearch</strong></div></div>
              <div className="horizontal-worktree" aria-label="横向研究工作树"><div className="worktree-track">{phases.map(([key,label],index)=>{const records=events.filter(e=>e.stage===key || (key==='execution' && e.stage==='results'));const current=lastPhase===key;return <div className="worktree-step" key={key}><button type="button" className={'worktree-card '+(records.length?'has-records ':'')+(current?'is-current':'')} onClick={()=>setSelectedPhase(key)} aria-label={'查看'+label+'详情'}><span className="worktree-number">{String(index+1).padStart(2,'0')}</span><strong>{label}</strong><span className="worktree-count">{records.length ? `${records.length} 条记录` : '等待推进'}</span></button>{records.slice(-2).map(record=><button className="worktree-branch" key={record.id} onClick={()=>setSelectedPhase(key)}><span>↳</span>{record.round>0 ? `第 ${record.round} 轮` : '研究记录'}<small>{record.summary || record.validation?.summary || record.revision?.summary || stageLabels[record.stage]}</small></button>)}</div>})}</div></div>
              {!events.length && <p className="waiting">正在读取研究记录…</p>}
              {terminal && <div className="completion"><span>✓</span><div><strong>本轮研究已结束</strong><p>{reasons[snapshot?.stop_reason] || snapshot?.stop_reason || '运行结束'}</p></div></div>}
            </>}
          </div>
          <div className="composer-wrap"><div className={'mascot-scene ' + (running ? 'is-computing' : '')} role="img" aria-label={running ? '小人正在快速敲击键盘' : '等待研究的小人'}><div className="composer-mascot coding-art" /><span className="typing-hand hand-left"/><span className="typing-hand hand-right"/><span className="typing-spark spark-one">⌁</span><span className="typing-spark spark-two">✦</span></div>
            {(error || snapshot?.error) && <p className="negative" role="alert">{error || snapshot.error}</p>}
            <form id="research-form" onSubmit={start} className="composer">
              <label className="sr-only" htmlFor="goal">研究目标</label><textarea id="goal" required maxLength={2000} rows={2} disabled={running} placeholder="描述你想研究的问题…" value={goal} onChange={e => setGoal(e.target.value)} />
              <div className="composer-actions"><span /><button disabled={running || !config} type="submit">{busy ? '启动中' : '开始研究'} <span>↑</span></button></div>
            </form>
          </div></>}
          {selectedPhase && <form className="phase-question-form" onSubmit={askPhase}><textarea aria-label="向本步骤提问" placeholder="针对这一步提问…" rows={2} value={phaseQuestions[selectedPhase] || ''} onChange={e=>setPhaseQuestions(values=>({...values,[selectedPhase]:e.target.value}))}/><div><span>记录查询 · 未接入对话模型</span><button type="submit" disabled={!(phaseQuestions[selectedPhase] || '').trim()}>发送 ↑</button></div></form>}
        </section>
        <aside className="right-column">
          <section className="panel progress-panel files-panel" aria-labelledby="files-title">
            <div className="right-heading"><h2 id="files-title"><span className="pixel-icon icon-folder"/>工作文件</h2><span className="files-icon">▤</span></div>
            <div className="files-scroll">
              <div className="file-section"><h3>输出内容 <span>{(snapshot?.results || []).filter(r=>r.artifact).length}</span></h3>
              {(snapshot?.results || []).filter(r=>r.artifact).map(result=><button className="file-row" key={result.candidate_id} onClick={()=>setSelectedPhase('execution')} title={result.artifact}><span className="file-symbol">▧</span><span><strong>{result.artifact.split('/').at(-1)}</strong><small>{result.error ? '执行失败记录' : '实验结果'}</small></span><span className="file-arrow">↗</span></button>)}
              {!(snapshot?.results || []).some(r=>r.artifact) && <p className="file-empty">运行后显示实验产物</p>}
              {terminal && <a className="file-row" href={`/runs/${encodeURIComponent(runId)}/artifacts`}><span className="file-symbol amber">↓</span><span><strong>研究包.zip</strong><small>配置、记录与实验结果</small></span></a>}</div>
              <div className="file-section"><h3>运行状态</h3><div className="file-row"><span className="file-symbol dark">⌘</span><span><strong>{status}</strong>{snapshot?.round > 0 && <small>第 {snapshot.round} 轮</small>}</span></div></div>
              <div className="file-section"><h3>来源 <span>{(snapshot?.task.resources || resources.split('\n').filter(Boolean)).length}</span></h3>{(snapshot?.task.resources || resources.split('\n').filter(Boolean)).map((resource,index)=><div className="file-row" key={index} title={resource}><span className="file-symbol">⌁</span><span><strong>{resource}</strong></span></div>)}{!(snapshot?.task.resources || resources.split('\n').filter(Boolean)).length && <p className="file-empty">暂无输入资源</p>}</div>
            </div>
          </section>
          <section className="panel metrics"><div className="right-heading"><div><h2><span className="pixel-icon icon-bars"/>资源用量</h2></div><span className="resource-icon">◴</span></div><div className="metrics-scroll"><dl>{usage.map(([label, value, max, unit, used]) => <div key={label} className={'usage-card usage-' + ({'运行时间':'time','工具调用':'tools','云端请求':'cloud','Token':'tokens'})[label]}><dt><span className="usage-label"><span className="usage-symbol" aria-hidden="true">{({'运行时间':'◷','工具调用':'⌘','云端请求':'☁','Token':'◇'})[label]}</span>{label}</span><span className="usage-value"><b>{value}</b><small>/ {max} {unit}</small></span></dt><dd><div className={'meter ' + (max > 0 && used/max >= .9 ? 'meter-warning' : '')}><i style={{width: `${max > 0 ? Math.min(100, used / max * 100) : 0}%`}} /></div><span className="usage-percent">{max > 0 ? `${Math.min(100, used/max*100).toFixed(0)}% 已用` : '未分配额度'}</span></dd></div>)}</dl><p className="pending">待确认 Token <b>{accounting.tokens_pending ?? snapshot?.tokens_pending ?? 0}</b></p>{terminal && <a className="download" href={`/runs/${encodeURIComponent(runId)}/artifacts`}>下载研究包 <span>↓</span></a>}</div></section>
        </aside>
      </div>
    </main>
  </>

}

createRoot(document.getElementById('root')).render(<App />)

import './pixel.css'
