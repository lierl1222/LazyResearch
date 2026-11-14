import React, {useEffect, useState} from 'react'
import {createRoot} from 'react-dom/client'
import {Workflow,Detail} from './Workflow.jsx'
import './style.css'
import './pixel.css'

let uploadSequence=0
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
  const [budget,setBudget] = useState({max_llm_calls:20,max_cloud_requests:20,max_llm_input_tokens:null,max_llm_output_tokens:12000,max_experiments:8,max_wall_time_seconds:300})
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
  const limits=data?.task.budget || budget
  const terminal=data && !['queued','running'].includes(data.status)
  async function start(e) {
    e.preventDefault();setError('');setBusy(true)
    try {
      if(files.some(f=>!f.id))throw new Error("请重试或移除上传失败的文件")
      const task={goal,domain:domain.trim() || '通用研究',budget,max_delegations:rounds,max_worker_turns:4,file_ids:files.map(f=>f.id)}
      const result=await request('/research/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(task)})
      setTabs([]);setFocus({});setDrafts({});setFiles([]);setRun(result.id);setData({status:'queued',events:[],task});setPhase(null)
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
        if(entry.file.size>(config?.max_file_bytes ?? 2000000))throw new Error('超过服务端文件大小上限')
        const meta=await request('/research/files?name='+encodeURIComponent(entry.name),{method:'POST',body:entry.file})
        setFiles(old=>old.flatMap(f=>f.key===entry.key?(meta.files || [meta]).map(item=>({...item,key:item.id,status:'已上传'})):[f]))
      }catch(e){setError(entry.name+" 上传失败："+e.message);setFiles(old=>old.map(f=>f.key===entry.key?{...f,status:e.message}:f))}
    }))
  }
  async function send(e) {
    e.preventDefault()
    setSending(true);setError('')
    try {
      await request('/research/runs/'+run+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({stage_id:phase,round_id:focus[phase]?.round ?? null,message:drafts[key]})})
      setDrafts(old=>({...old,[key]:''}))
      setData(await request('/research/runs/'+run))
    }catch(e){setError(e.message)}finally{setSending(false)}
  }
  function newTask(){
    setRun(null);setData(null);setGoal('');setDomain('');setPhase(null);setError('')
    history.replaceState(null,'',location.pathname)
  }
  const metrics=[
    ['运行时间',Number(used.wall_seconds || data?.elapsed || 0).toFixed(1),limits.max_wall_time_seconds,'秒'],
    ['云端请求',used.cloud_requests || 0,limits.max_cloud_requests ?? limits.max_llm_calls,'次'],
    ['实验次数',used.experiment_count || 0,limits.max_experiments,'次'],
    ['模型调用',used.llm_calls || 0,limits.max_llm_calls,'次','calls'],
    ['输入 Token',used.input_tokens || 0,limits.max_llm_input_tokens,''],
    ['输出 Token',used.output_tokens || 0,limits.max_llm_output_tokens,'','output_tokens'],
  ]
  return <>
    <header><div className="brand"><span className="header-logo pixel-round-logo" role="img" aria-label="LazyResearch"/><span className="brand-name">LazyResearch</span></div><span className="mode"><i/>{config?'LLM 研究引擎':'连接中'}</span></header>
    <main><div className="layout">
      <aside className="panel settings"><div className="panel-heading"><i className="pixel-icon icon-flask"/><h2>研究空间</h2></div><div className="settings-scroll">
        <label>研究领域<input required maxLength={160} disabled={!!data||busy} value={domain} placeholder="如水声通信、材料科学" onChange={e=>setDomain(e.target.value)}/></label>
        <fieldset disabled={!!data||busy}><legend><i className="pixel-icon icon-coins"/>预算配置</legend><div className="limits"><label>研究轮数<input type="number" form="research-form" min="1" max="20" required value={data?.task.max_delegations || rounds} onChange={e=>setRounds(Number(e.target.value))}/></label>{[['max_cloud_requests','云端请求',0,100],['max_llm_calls','模型调用',1,100],['max_experiments','实验次数',1,100],['max_wall_time_seconds','时间（秒）',1,3600],['max_llm_input_tokens','输入 Token',1,1000000],['max_llm_output_tokens','输出 Token',1,100000]].map(([key,label,min,max])=><label key={key}>{label}<input form="research-form" type="number" required={key!=='max_llm_input_tokens'} placeholder={key==='max_llm_input_tokens'?'—':undefined} min={min} max={max} value={limits[key] ?? ''} onChange={e=>setBudget({...budget,[key]:e.target.value===''&&key==='max_llm_input_tokens'?null:Number(e.target.value)})}/></label>)}</div></fieldset>
        <p><i className="metric-pixel" aria-hidden="true"/>模型配置 {config?.models.local.ready?'本地已配置':'本地未配置'} · {config?.models.cloud.ready?'云端已配置':'云端未配置'}</p>
      </div><div className="sidebar-footer">服务{config?'已连接':'连接中'}</div></aside>
      <section className="panel conversation" aria-label="研究工作区">
        {data&&<nav className="session-tabs"><button aria-current={!phase} onClick={()=>setPhase(null)}>研究对话</button>
          {tabs.map(id=><span key={id}><button aria-current={phase===id} onClick={()=>setPhase(id)}>{nodes.find(n=>n.id===id)?.name}</button><button aria-label="关闭详情" onClick={()=>{setTabs(old=>old.filter(t=>t!==id));if(phase===id)setPhase(null)}}>×</button></span>)}
        </nav>}
        <div className="messages" role="log">
          {!data?<div className="welcome"><div className="welcome-mascot coding-art" role="img" aria-label="研究助手"/><h1>你的下一个发现，从这里开始。</h1></div>:<>
            {node?<><button onClick={()=>setPhase(null)}>返回流程总览</button>{focus[phase]?.round!=null&&<button onClick={()=>open(phase)}>显示全部轮次</button>}
              <Detail node={node} index={nodes.indexOf(node)} focus={focus[phase]} events={events}/></>:<>
              <div className="user-message"><p>{data.task.goal}</p></div><Workflow nodes={nodes} open={open}/>
              {data.result&&<article className="reply"><h3>研究结果</h3>{data.result.split('\n').slice(1).filter(Boolean).map((line,i)=>line.startsWith('## ')?<h4 key={i}>{line.slice(3)}</h4>:<p key={i}>{line}</p>)}<a href={'/research/runs/'+run+'/result.md'}>下载研究结果.md</a></article>}
            </>}
            {(data.exchanges||[]).filter(x=>!phase||x.stage===phase).map(x=><article key={x.id}><div className="user-message"><p>{x.message}</p></div><p className="reply">{x.answer}</p></article>)}
          </>}
        </div>
        <div className="composer-wrap"><div className={'mascot-scene '+(running?'is-computing':'')}><div className="composer-mascot coding-art"/></div>
        {error&&<p className="negative" role="alert">{error}</p>}
        {data?<form className="composer" onSubmit={send}><textarea aria-label="研究提问" required maxLength={1500} value={drafts[key]||''} onChange={e=>setDrafts({...drafts,[key]:e.target.value})} placeholder={node?'针对该阶段提问…':'向研究助手提问…'}/>
          <div className="composer-actions">{running?<button type="button" onClick={stop}>停止研究</button>:<button type="button" disabled={sending} onClick={newTask}>新建研究</button>}<button disabled={sending||!drafts[key]?.trim()}>{sending?'回答中':'发送'}</button></div></form>:
          <form id="research-form" onSubmit={start} className="composer" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(!busy)upload(e.dataTransfer.files)}}>
          <textarea aria-label="研究任务" required maxLength={3000} disabled={busy} rows={2} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="描述具体研究任务…"/>
          <div className="composer-actions"><label className="attach"><i className="pixel-icon icon-folder"/>上传文件<input type="file" multiple disabled={busy} accept=".csv,.tsv,.md,.txt,.json,.zip" onChange={e=>{upload(e.target.files);e.target.value=''}}/></label>
          <div className="attached">{files.map(f=><span key={f.key}>{f.name} · {f.name.split('.').pop().toUpperCase()} · {f.status}<button type="button" aria-label={'移除 '+f.name} onClick={()=>setFiles(old=>old.filter(x=>x.key!==f.key))}>×</button></span>)}</div>
          <button disabled={busy||!!run||!config||files.length>12||files.some(f=>f.status==='上传中')} type="submit">{busy?'提交中':'开始研究'} ↑</button></div>{files.length>12&&<p>每个任务最多 12 个文件</p>}</form>}
        </div>
      </section>
      <aside className="right-column"><section className="panel progress-panel files-panel"><div className="right-heading"><i className="pixel-icon icon-folder"/><h2>工作文件</h2></div><div className="files-scroll">
        <div className="file-section"><h3>运行状态</h3><p>{statusLabels[data?.status]||'等待启动'}</p></div>
        {data?.task.files?.map(f=><div className="file-row" key={f.id}><i className="pixel-icon icon-folder"/>{f.name}</div>)}
        <div className="file-section"><h3>验证记录</h3>{events.filter(e=>e.observation_id).map(e=><button className="file-row" key={e.id} onClick={()=>open('validation',e.round,e.id)}><span>{e.observation_id}</span><small>{e.summary}</small></button>)}</div>
        {run&&<a className="file-row" target="_blank" rel="noreferrer" href={'/research/runs/'+run+'/report'}>实时运行报告 ↗</a>}{terminal&&<a className="file-row" href={'/research/runs/'+run+'/result.md'}>研究结果.md ↓</a>}{terminal&&<a className="file-row" href={'/research/runs/'+run+'/artifacts'}>下载研究包.zip ↓</a>}
      </div></section>
      <section className="panel metrics"><div className="right-heading"><i className="pixel-icon icon-bars"/><h2>资源用量</h2></div><div className="metrics-scroll"><dl>{metrics.map(([label,value,max,unit,field])=><div className="usage-card" key={label}><dt><span><i className="metric-pixel" aria-hidden="true"/>{label}</span><span className="usage-value"><b>{value}</b><small>/ {max ?? '—'} {unit}</small></span></dt><dd>{max!=null&&<div className="meter"><i style={{width:Math.min(100,max?value/max*100:0)+'%'}}/></div>}{field&&<div className="usage-split">{[['cloud','云端'],['local','本地'],['unknown','来源未知']].filter(([role])=>role!=='unknown'||used.by_model?.unknown).map(([role,name])=><span key={role}>{name} <strong>{(used.by_model?.[role]?.[field] ?? 0).toLocaleString()}</strong>{field==='calls'?' 次':''}</span>)}</div>}</dd></div>)}</dl><p>API 费用 {used.api_cost_usd==null?'未配置计价或用量未知':'$'+used.api_cost_usd.toFixed(6)}</p>{used.unknown_usage_calls>0&&<p>含 {used.unknown_usage_calls} 次预留估算用量</p>}</div></section></aside>
    </div></main>
  </>
}
createRoot(document.getElementById('root')).render(<App/>)
