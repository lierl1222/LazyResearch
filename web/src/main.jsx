import React, {useEffect, useState} from 'react'
import {createRoot} from 'react-dom/client'
import {Workflow,Detail} from './Workflow.jsx'
import './style.css'
import './pixel.css'

let uploadSequence=0
function inline(text){
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((part,i)=>
    part.startsWith('**')&&part.endsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>
    :part.startsWith('`')&&part.endsWith('`')?<code key={i}>{part.slice(1,-1)}</code>
    :part)
}
function Markdown({text}) {
  const blocks=[];let table=null
  const flushTable=()=>{if(table){blocks.push(<table key={blocks.length}><tbody>{table.map((row,r)=><tr key={r}>{row.map((cell,c)=><td key={c}>{inline(cell)}</td>)}</tr>)}</tbody></table>);table=null}}
  for(const line of text.replace(/^#[^\n]*\n/,'').split('\n')){
    const trimmed=line.trim()
    if(!trimmed){flushTable();continue}
    if(/^\|.*\|$/.test(trimmed)){const cells=trimmed.split('|').slice(1,-1).map(s=>s.trim())
      if(!cells.every(c=>/^:?-+:?$/.test(c)))(table||(table=[])).push(cells);continue}
    flushTable()
    if(trimmed.startsWith('## '))blocks.push(<h4 key={blocks.length}>{inline(trimmed.slice(3))}</h4>)
    else if(trimmed.startsWith('### '))blocks.push(<h5 key={blocks.length}>{inline(trimmed.slice(4))}</h5>)
    else if(trimmed.startsWith('- '))blocks.push(<p className="bullet" key={blocks.length}>{inline(trimmed.slice(2))}</p>)
    else if(trimmed.startsWith('> '))blocks.push(<p className="quote" key={blocks.length}>{inline(trimmed.slice(2))}</p>)
    else blocks.push(<p key={blocks.length}>{inline(trimmed)}</p>)
  }
  flushTable()
  return <>{blocks}</>
}
const statusLabels = {queued:'排队中',running:'研究中',reported:'报告已生成',inconclusive:'证据不足',stopped:'研究已停止',failed:'执行失败',unsupported:'缺少可用工具'}
async function request(url, options) {
  const response = await fetch(url, options)
  const data = await response.json()
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(v=>v.msg).join('，') : data.detail || '请求失败')
  return data
}
function App() {
  const [config,setConfig] = useState(null)
  const [domain,setDomain] = useState('')
  const [goal,setGoal] = useState('')
  const [files,setFiles] = useState([])
  const [rounds,setRounds] = useState(4)
  const [tabs,setTabs] = useState([])
  const [focus,setFocus] = useState({})
  const [drafts,setDrafts] = useState({})
  const [sending,setSending] = useState(false)
  const [budget,setBudget] = useState({max_llm_calls:null,max_cloud_requests:20,max_llm_input_tokens:null,max_llm_output_tokens:12000,max_experiments:8,max_wall_time_seconds:300})
  const [run,setRun] = useState(new URLSearchParams(location.search).get('research'))
  const [data,setData] = useState(null)
  const [phase,setPhase] = useState(null)
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  useEffect(()=>{request('/research/config').then(setConfig).catch(e=>setError(e.message))},[])
  useEffect(()=>{
    if(!run)return
    let active=true, timer
    async function sync() {
      try {
        const value=await request('/research/runs/'+encodeURIComponent(run))
        if(!active)return
        setData(value)
        setDomain(value.task.domain || "")
        if(['queued','running'].includes(value.status))timer=setTimeout(sync,1000)
      } catch(e) {if(active)setError(e.message)}
    }
    sync()
    return ()=>{active=false;clearTimeout(timer)}
  },[run])
  const running=busy || ['queued','running'].includes(data?.status)
  const events=data?.events || []
  const used=data?.budget || {}
  const limits=running ? data?.task.budget || budget : budget
  const usageLimits=data?.task.budget || budget
  const terminal=data && !['queued','running'].includes(data.status)
  const draft = data ? drafts[phase || 'conversation'] || '' : goal
  const inheritedCount = (data?.task.attachments ?? data?.task.files)?.length || 0
  const fileCount = inheritedCount + files.length
  const canResearch = !!config && (!run || terminal) && !busy && !sending && !!draft.trim() &&
    draft.length <= 3000 && fileCount <= 12 && files.every(file=>file.id)
  async function start(e) {
    e.preventDefault()
    if (!canResearch) return
    setError('');setBusy(true)
    try {
      const task={goal:draft,domain:domain.trim() || '通用研究',budget,max_delegations:rounds,max_worker_turns:4,file_ids:files.map(f=>f.id)}
      if(run)task.previous_run_id=run
      const result=await request('/research/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(task)})
      setTabs([]);setFocus({});setDrafts({});setFiles([]);setRun(result.id)
      setData({status:'queued',events:[],task,exchanges:data?.exchanges,
        research_history:data?[...(data.research_history||[]),{id:run,goal:data.task.goal}]:[]})
      setPhase(null)
      history.replaceState(null,'','?research='+result.id)
    } catch(e) {setError(e.message)} finally {setBusy(false)}
  }
  async function stop() {
    try {await request('/research/runs/'+run+'/stop',{method:'POST'})}catch(e){setError(e.message)}
  }
  const nodes=data?.workflow || []
  const node=nodes.find(n=>n.id===phase)
  const key=phase || 'conversation'
  function open(id,round=null,record=null) {
    setTabs(old=>old.includes(id)?old:[...old,id])
    setPhase(id)
    setFocus(old=>({...old,[id]:{round,record}}))
  }
  useEffect(()=>{
    const record=focus[phase]?.record
    if(record)document.getElementById('record-'+record)?.scrollIntoView({block:'nearest'})
  },[phase,focus])
  async function upload(selected) {
    const batch=Array.from(selected).map(file=>({file,name:file.name,key:globalThis.crypto?.randomUUID?.() ?? (++uploadSequence),status:'上传中'}))
    setFiles(old=>[...old,...batch])
    await Promise.all(batch.map(async entry=>{
      try {
        if(entry.file.size>(entry.name.toLowerCase().endsWith('.zip') ? config.max_archive_bytes : config.max_file_bytes))throw new Error('超过服务端文件大小上限')
        const meta=await request('/research/files?name='+encodeURIComponent(entry.name),{method:'POST',body:entry.file})
        setFiles(old=>old.map(f=>f.key===entry.key?{...meta,key:meta.id,status:'已上传'}:f))
      }catch(e){setError(entry.name+" 上传失败："+e.message);setFiles(old=>old.map(f=>f.key===entry.key?{...f,status:e.message}:f))}
    }))
  }
  async function send(e) {
    e.preventDefault()
    if (!run || sending || !draft.trim() || draft.length > 1500) return
    setSending(true);setError('')
    try {
      await request('/research/runs/'+run+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({stage_id:phase,round_id:focus[phase]?.round ?? null,message:draft,local_only:true})})
      setDrafts(old=>({...old,[key]:''}))
      setData(await request('/research/runs/'+run))
    }catch(e){setError(e.message)}finally{setSending(false)}
  }
  function newTask(){
    setRun(null);setData(null);setGoal('');setDomain('');setPhase(null);setError('')
    setTabs([]);setFocus({});setDrafts({});setFiles([])
    history.replaceState(null,'',location.pathname)
  }
  const metrics=[
    ['运行时间',Number(used.wall_seconds || data?.elapsed || 0).toFixed(1),usageLimits.max_wall_time_seconds,'秒'],
    ['云端请求',used.cloud_requests || 0,usageLimits.max_cloud_requests,'次'],
    ['实验次数',used.experiment_count || 0,usageLimits.max_experiments,'次'],
    ['模型调用',used.llm_calls || 0,usageLimits.max_llm_calls,'次','calls'],
    ['输入 Token',used.input_tokens || 0,usageLimits.max_llm_input_tokens,''],
    ['输出 Token',used.output_tokens || 0,usageLimits.max_llm_output_tokens,'','output_tokens'],
  ]
  return <>
    <header><div className="brand"><span className="header-logo pixel-round-logo" role="img" aria-label="LazyResearch"/><span className="brand-name">LazyResearch</span></div><button className="new-research" type="button" disabled={busy||sending} onClick={newTask}>＋ 新建研究</button></header>
    <main><div className="layout">
      <aside className="panel settings"><div className="panel-heading"><i className="pixel-icon icon-flask"/><h2>研究空间</h2></div><div className="settings-scroll">
        <label>研究领域<input maxLength={160} disabled={running} value={domain} placeholder="如数据分析、机器学习" onChange={e=>setDomain(e.target.value)}/></label>
        <fieldset disabled={running}><legend><i className="pixel-icon icon-coins"/>预算配置</legend><div className="limits"><label>研究轮数<input type="number" form="research-form" min="1" max="20" required value={running ? data?.task.max_delegations || rounds : rounds} onChange={e=>setRounds(Number(e.target.value))}/></label>
          <label>模型调用<input readOnly value="—" title="模型调用总数无上限"/></label>
          {[['max_cloud_requests','云端请求',0,100],['max_experiments','实验次数',1,100],['max_wall_time_seconds','时间（秒）',1,3600],['max_llm_input_tokens','输入 Token',1,1000000],['max_llm_output_tokens','输出 Token',1,100000]].map(([key,label,min,max])=><label key={key}>{label}<input form="research-form" type="number" required={key!=='max_llm_input_tokens'} placeholder={key==='max_llm_input_tokens'?'—':undefined} min={min} max={max} value={limits[key] ?? ''} onChange={e=>setBudget({...budget,[key]:e.target.value===''&&key==='max_llm_input_tokens'?null:Number(e.target.value)})}/></label>)}</div></fieldset>
        <p>本地模型：{config ? config.models.local.model || '未配置' : '—'}<br/>
          云端模型：{config ? config.models.cloud.model || '未配置' : '—'}</p>
      </div><div className="sidebar-footer">服务{config?'已连接':'连接中'}</div></aside>
      <section className="panel conversation" aria-label="研究工作区">
        {data&&<nav className="session-tabs"><button aria-current={!phase} onClick={()=>setPhase(null)}>研究对话</button>
          {tabs.map(id=><span key={id}><button aria-current={phase===id} onClick={()=>setPhase(id)}>{nodes.find(n=>n.id===id)?.name}</button><button aria-label="关闭详情" onClick={()=>{setTabs(old=>old.filter(t=>t!==id));if(phase===id)setPhase(null)}}>×</button></span>)}
        </nav>}
        <div className="messages" role="log">
          {!data?<div className="welcome"><div className="welcome-mascot coding-art" role="img" aria-label="研究助手"/><h1>你的下一个发现，从这里开始。</h1></div>:<>
            {node?<><button onClick={()=>setPhase(null)}>返回流程总览</button>{focus[phase]?.round!=null&&<button onClick={()=>open(phase)}>显示全部轮次</button>}
              <Detail node={node} index={nodes.indexOf(node)} focus={focus[phase]} events={events}/></>:<>
              {!!data.research_history?.length&&<details className="research-history"><summary>此前研究（{data.research_history.length} 次）</summary><ul>
                {data.research_history.map((item,i)=><li key={item.id}><a href={'?research='+item.id} target="_blank" rel="noreferrer">第 {i+1} 次 · {item.goal}</a></li>)}
              </ul></details>}
              <div className="user-message"><p>{data.task.goal}</p></div><Workflow nodes={nodes} open={open}/>
              {data.result&&<article className="reply"><h3>研究报告</h3><Markdown text={data.result}/><a href={'/research/runs/'+run+'/result.md'}>下载研究报告.md</a></article>}
            </>}
            {(data.exchanges||[]).filter(x=>!phase||(x.stage===phase&&(!x.run_id||x.run_id===run))).map(x=><article key={x.id}><div className="user-message"><p>{x.message}</p></div><p className="reply">{x.answer}</p></article>)}
          </>}
        </div>
        <div className="composer-wrap"><div className={'mascot-scene '+(running?'is-computing':'')}><div className="composer-mascot coding-art"/></div>
        {error&&<p className="negative" role="alert">{error}</p>}
          <form id="research-form" onSubmit={start} className="composer" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(!running)upload(e.dataTransfer.files)}}>
          <textarea aria-label="研究任务或对话内容" required maxLength={3000} disabled={busy} rows={2} value={draft}
            onChange={e=>data?setDrafts({...drafts,[key]:e.target.value}):setGoal(e.target.value)}
            placeholder={!data?'描述具体研究任务…':node?'针对该阶段提问或继续研究…':'输入后续研究目标，或与本地模型对话…'}/>
          <div className="composer-actions"><label className="attach"><i className="pixel-icon icon-folder"/>上传文件<input type="file" multiple disabled={running} onChange={e=>{upload(e.target.files);e.target.value=''}}/></label>
          <div className="attached">{files.map(f=><span key={f.key}>{f.name} · {f.name.split('.').pop().toUpperCase()} · {f.status}<button type="button" aria-label={'移除 '+f.name} onClick={()=>setFiles(old=>old.filter(x=>x.key!==f.key))}>×</button></span>)}</div>
          {run&&running?<button type="button" disabled={busy} onClick={stop}>停止研究</button>:<button disabled={!canResearch} type="submit">{busy?'提交中':'研究'}</button>}
          {data&&<button type="button" onClick={send} title={config?.models.local.ready?'使用本地模型与当前窗口的记忆对话':'本地模型未配置'}
            disabled={busy||sending||!config?.models.local.ready||!draft.trim()||draft.length>1500}>{sending?'回答中':'对话'}</button>}</div>
          {fileCount>12&&<p>每个研究窗口最多使用 12 个附件（含此前上传的附件）</p>}</form>
        </div>
      </section>
      <aside className="right-column"><section className="panel progress-panel files-panel"><div className="right-heading"><i className="pixel-icon icon-folder"/><h2>工作文件</h2></div><div className="files-scroll">
        <div className="file-section"><h3>运行状态</h3><p>{statusLabels[data?.status]||'等待启动'}</p></div>
        {(data?.task.attachments ?? data?.task.files)?.map(f=><div className="file-row" key={f.id}><i className="pixel-icon icon-folder"/>{f.name}</div>)}
        <div className="file-section"><h3>验证记录</h3>{events.filter(e=>e.stage==='validation'&&e.outcome).map(e=><button className="file-row evidence-row" key={e.id} onClick={()=>open('validation',e.round,e.id)}><strong>{e.display.title}</strong><small>{e.display.summary}{e.display.fields.length>0&&' · '+e.display.fields.slice(0,2).map(({label,value})=>label+' '+value).join(' · ')}</small></button>)}</div>
        {run&&<a className="file-row" target="_blank" rel="noreferrer" href={'/research/runs/'+run+'/report'}>实时运行报告 ↗</a>}{terminal&&<a className="file-row" href={'/research/runs/'+run+'/result.md'}>研究报告.md ↓</a>}{terminal&&<a className="file-row" href={'/research/runs/'+run+'/artifacts'}>下载研究包.zip ↓</a>}
      </div></section>
      <section className="panel metrics"><div className="right-heading"><i className="pixel-icon icon-bars"/><h2>资源用量</h2></div><div className="metrics-scroll"><dl>{metrics.map(([label,value,max,unit,field])=><div className="usage-card" key={label}><dt><span><i className="metric-pixel" aria-hidden="true"/>{label}</span><span className="usage-value"><b>{value}</b><small>/ {max ?? '—'} {unit}</small></span></dt><dd>{max!=null&&<div className="meter"><i style={{width:Math.min(100,max?value/max*100:0)+'%'}}/></div>}{field&&<div className="usage-split">{[['cloud','云端'],['local','本地'],['unknown','来源未知']].filter(([role])=>role!=='unknown'||used.by_model?.unknown).map(([role,name])=><span key={role}>{name} <strong>{(used.by_model?.[role]?.[field] ?? 0).toLocaleString()}</strong>{field==='calls'?' 次':''}</span>)}</div>}</dd></div>)}</dl>{used.unknown_usage_calls>0&&<p>含 {used.unknown_usage_calls} 次预留估算用量</p>}</div></section></aside>
    </div></main>
  </>
}
createRoot(document.getElementById('root')).render(<App/>)
