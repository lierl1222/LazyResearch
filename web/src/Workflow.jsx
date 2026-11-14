import React from 'react'

export function Workflow({nodes, open}) {
  return <div className="horizontal-worktree"><div className="worktree-track">
    {nodes.map((node,i)=><div className="worktree-step" key={node.id}>
      <button className={'worktree-card '+(node.records.length?'has-records ':'')+(node.status==='执行中'?'is-current':'')} onClick={()=>open(node.id)}>
        <small>{i+1} · {node.status}</small><strong>{node.name}</strong><span>{node.records.length} 条记录</span>
      </button>{node.records.map(e=><button className="worktree-branch" key={e.id} onClick={()=>open(node.id,e.round,e.id)}>
        第 {e.round} 轮<small>{e.summary}</small></button>)}
    </div>)}
  </div></div>
}

export function Detail({node,index,focus,events}) {
  const records=node.records.filter(e=>focus?.round==null || e.round===focus.round)
  return <><h2>{index+1} · {node.name}</h2>{!records.length&&<p>等待阶段记录</p>}
    {records.map(e=><article className="reply detail-record" id={'record-'+e.id} key={e.id}>
      <h3>第 {e.round} 轮 · 记录 {e.id}</h3><p>{e.summary}</p>
      {e.prediction&&<p>{e.prediction}</p>}{[e.arguments,e.outcome,e.decision].filter(Boolean).map((v,i)=><pre className="research-json" key={i}>{JSON.stringify(v,null,2)}</pre>)}
      {node.id!=='validation'&&events.filter(v=>v.stage==='validation'&&v.round===e.round).map(v=><details key={v.id}><summary>同轮验证 · {v.observation_id}</summary><pre>{JSON.stringify(v.outcome,null,2)}</pre></details>)}
    </article>)}</>
}
