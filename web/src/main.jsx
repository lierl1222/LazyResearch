import React, {useEffect, useState} from 'react'
import {createRoot} from 'react-dom/client'
import './style.css'
import './pixel.css'

const phases = [['plan','研究规划'],['hypothesis','提出假设'],['execution','实验或分析'],['validation','独立验证'],['revision','修正']]
const statusLabels = {queued:'排队中',running:'研究中',reported:'报告已生成',inconclusive:'证据不足',stopped:'研究已停止',failed:'执行失败',unsupported:'缺少可用工具'}
const modes = {sequence:'数学猜想 · 数列',cpu:'CPU 性能实验',tabular:'表格分类研究'}
async function request(url, options) {
  const response = await fetch(url, options)
  const data = await response.json()
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(v=>v.msg).join('，') : data.detail || '请求失败')
  return data
}
function App() {
  const [config,setConfig] = useState(null)
  const [mode,setMode] = useState('sequence')
  const [goal,setGoal] = useState('研究给定数列的多项式规律，检验竞争假设并报告适用范围')
  const [sequence,setSequence] = useState('1, 2, 5, 10, 17, 26')
  const [csv,setCsv] = useState('')
  const [fileName,setFileName] = useState('')
  const [target,setTarget] = useState('y')
  const [positive,setPositive] = useState('1')
  const [budget,setBudget] = useState({max_llm_calls:20,max_llm_input_tokens:60000,max_llm_output_tokens:12000,max_experiments:8,max_wall_time_seconds:300})
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
      const task={goal,budget,max_delegations:4,max_worker_turns:4}
      if(mode==='sequence') {
        task.sequence=sequence.split(/[，,\s]+/).filter(Boolean).map(Number)
        if(!task.sequence.length || task.sequence.some(v=>!Number.isSafeInteger(v)))throw new Error('请输入整数数列')
      }
      if(mode==='cpu')task.cpu_benchmark=true
      if(mode==='tabular') {
        if(!csv)throw new Error('请上传 CSV')
        task.csv_text=csv;task.target=target
        task.positive_label=/^-?\d+(\.\d+)?$/.test(positive)?Number(positive):positive
      }
      const result=await request('/research/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(task)})
      setRun(result.id);setData({status:'queued',events:[],task});setPhase(null)
      history.replaceState(null,'','?research='+result.id)
    } catch(e) {setError(e.message)} finally {setBusy(false)}
  }
  async function stop() {
    try {await request('/research/runs/'+run+'/stop',{method:'POST'})}catch(e){setError(e.message)}
  }
  const metrics=[
    ['运行时间',Number(used.wall_seconds || data?.elapsed || 0).toFixed(1),limits.max_wall_time_seconds,'秒'],
    ['实验次数',used.experiment_count || 0,limits.max_experiments,'次'],
    ['模型调用',used.llm_calls || 0,limits.max_llm_calls,'次'],
    ['输入 Token',used.input_tokens || 0,limits.max_llm_input_tokens,''],
    ['输出 Token',used.output_tokens || 0,limits.max_llm_output_tokens,''],
  ]
  return <>
    <header><div className="brand"><span className="header-logo pixel-round-logo" role="img" aria-label="LazyResearch"/><span className="brand-name">LazyResearch</span></div><span className="mode"><i/>{config?'LLM 研究引擎':'连接中'}</span></header>
    <main><div className="layout">
      <aside className="panel settings"><div className="panel-heading"><h2>研究空间</h2></div><div className="settings-scroll">
        <label>研究场景<select disabled={running} value={mode} onChange={e=>{setMode(e.target.value);setGoal(e.target.value==='cpu'?'比较成员查询算法，验证正确性并提高执行速度':e.target.value==='tabular'?'分析数据并验证改善分类表现的假设':'研究给定数列的多项式规律并寻找反例')}}>{Object.entries(modes).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        {mode==='sequence'&&<label>整数数列<textarea disabled={running} rows={3} value={sequence} onChange={e=>setSequence(e.target.value)}/></label>}
        {mode==='cpu'&&<p>在相同输入下比较 list、set 和排序索引，测量包含索引构建的查询时间。</p>}
        {mode==='tabular'&&<><label>CSV 文件<input disabled={running} type="file" accept=".csv" onChange={async e=>{const file=e.target.files[0];if(!file)return;if(file.size>2000000){setError('CSV 请控制在 2 MB 内');return}setCsv(await file.text());setFileName(file.name)}}/>{fileName}</label><label>目标列<input disabled={running} value={target} onChange={e=>setTarget(e.target.value)}/></label><label>正类标签<input disabled={running} value={positive} onChange={e=>setPositive(e.target.value)}/></label></>}
        <fieldset disabled={running}><legend>预算配置</legend><div className="limits">{[['max_llm_calls','模型调用',1,100],['max_experiments','实验次数',1,100],['max_wall_time_seconds','时间（秒）',1,3600],['max_llm_input_tokens','输入 Token',1,1000000],['max_llm_output_tokens','输出 Token',1,100000]].map(([key,label,min,max])=><label key={key}>{label}<input form="research-form" type="number" required min={min} max={max} value={budget[key]} onChange={e=>setBudget({...budget,[key]:Number(e.target.value)})}/></label>)}</div></fieldset>
        <p>模型配置 {config?.models.local.ready?'本地已配置':'本地未配置'} · {config?.models.cloud.ready?'云端已配置':'云端未配置'}</p>
      </div><div className="sidebar-footer">服务{config?'已连接':'连接中'}</div></aside>
      <section className="panel conversation" aria-label="研究工作区">
        <div className="messages" role="log">
          {!data?<div className="welcome"><div className="welcome-mascot coding-art" role="img" aria-label="研究助手"/><h1>你的下一个发现，从这里开始。</h1></div>:<>
            <div className="user-message"><p>{data.task?.goal}</p></div>
            <div className="horizontal-worktree"><div className="worktree-track">{phases.map(([key,label])=><div className="worktree-step" key={key}><button className={'worktree-card '+(events.some(e=>e.stage===key)?'has-records ':'')+(phase===key?'is-current':'')} onClick={()=>setPhase(phase===key?null:key)}><strong>{label}</strong><span>{events.filter(e=>e.stage===key).length} 条记录</span></button></div>)}</div></div>
            {phase&&<button onClick={()=>setPhase(null)}>查看全部记录</button>}
            {events.filter(e=>!phase||e.stage===phase).map(event=><article className="reply detail-record" key={event.id}><div className="event-head"><h3>{Object.fromEntries(phases)[event.stage]||({task:'研究材料',model_request:'请求模型',conclusion:'研究结论',model:'模型调用',running:'研究启动',queued:'任务排队',finished:'研究结束'})[event.stage]}</h3><span>{event.round?'委派 '+event.round:''}</span></div><p>{event.summary}</p>{event.prediction&&<p>{event.prediction}</p>}{event.reason&&<p className="negative">{event.reason}</p>}{(event.outcome||event.arguments)&&<details><summary>{event.observation_id||'实验参数'}</summary><pre className="research-json">{JSON.stringify(event.outcome||event.arguments,null,2)}</pre></details>}</article>)}
            {data.report&&<article className="reply"><h3>{statusLabels[data.status]}</h3><p>{data.report.summary}</p><p className="refs">证据引用 {(data.report.citations||[]).join(' · ')||'暂无'}</p></article>}
          </>}
        </div>
        <div className="composer-wrap"><div className={'mascot-scene '+(running?'is-computing':'')}><div className="composer-mascot coding-art"/></div>{error&&<p className="negative" role="alert">{error}</p>}
          <form id="research-form" onSubmit={start} className="composer"><label className="sr-only" htmlFor="goal">研究目标</label><textarea id="goal" required maxLength={3000} disabled={running} rows={2} value={goal} onChange={e=>setGoal(e.target.value)}/><div className="composer-actions">{running&&<button type="button" onClick={stop}>停止研究</button>}<button disabled={running||!config} type="submit">{busy?'提交中':'开始研究'} ↑</button></div></form>
        </div>
      </section>
      <aside className="right-column"><section className="panel progress-panel files-panel"><div className="right-heading"><h2>工作文件</h2></div><div className="files-scroll">
        <div className="file-section"><h3>运行状态</h3><p>{statusLabels[data?.status]||'等待启动'}</p></div>
        <div className="file-section"><h3>验证记录</h3>{events.filter(e=>e.observation_id).map(e=><button className="file-row" key={e.id} onClick={()=>setPhase('validation')}><span>{e.observation_id}</span><small>{e.summary}</small></button>)}</div>
        {run&&<a className="file-row" target="_blank" rel="noreferrer" href={'/research/runs/'+run+'/report'}>实时运行报告 ↗</a>}{terminal&&<a className="file-row" href={'/research/runs/'+run+'/artifacts'}>下载研究包.zip ↓</a>}
      </div></section>
      <section className="panel metrics"><div className="right-heading"><h2>资源用量</h2></div><div className="metrics-scroll"><dl>{metrics.map(([label,value,max,unit])=><div className="usage-card" key={label}><dt><span>{label}</span><span className="usage-value"><b>{value}</b><small>/ {max} {unit}</small></span></dt><dd><div className="meter"><i style={{width:Math.min(100,max?value/max*100:0)+'%'}}/></div></dd></div>)}</dl><p>API 费用 {used.api_cost_usd==null?'未配置计价或用量未知':'$'+used.api_cost_usd.toFixed(6)}</p>{used.unknown_usage_calls>0&&<p>含 {used.unknown_usage_calls} 次预留估算用量</p>}</div></section></aside>
    </div></main>
  </>
}
createRoot(document.getElementById('root')).render(<App/>)
