import React from 'react'

export function ObservationFields({fields = []}) {
  if (!fields.length) return null
  return <dl className="observation-fields">{fields.map(({label,value})=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
}

export function Workflow({nodes, open}) {
  return <div className="horizontal-worktree"><div className="worktree-track">
    {nodes.map((node,i)=><div className="worktree-step" key={node.id}>
      <button className={'worktree-card '+(node.records.length?'has-records ':'')+(node.status==='执行中'?'is-current':'')} onClick={()=>open(node.id)}>
        <small>{i+1} · {node.status}</small><strong>{node.name}</strong><span>{node.records.length} 条记录</span>
      </button>{node.records.map(e=><button className="worktree-branch" key={e.id} onClick={()=>open(node.id,e.round,e.id)}>
        {e.display?.title}<small>{e.display?.summary}</small></button>)}
    </div>)}
  </div></div>
}

export function Detail({node,index,focus,events}) {
  const records=node.records.filter(e=>focus?.round==null || e.round===focus.round)
  return <><h2>{index+1} · {node.name}</h2>{!records.length&&<p>{node.status==='未触发'?'本次研究未记录到需要修正的验证反馈。':'等待阶段记录'}</p>}
    {records.map(e=><article className="reply detail-record" id={'record-'+e.id} key={e.id}>
      <h3>{e.display?.title}</h3><p>{e.display?.summary}</p>
      <ObservationFields fields={e.display?.fields}/>
      {node.id!=='validation'&&events.filter(v=>v.stage==='validation'&&v.round===e.round&&v.outcome).map(v=><details key={v.id}>
        <summary>{v.display.title} · {v.display.summary}</summary>
        <ObservationFields fields={v.display.fields}/>
      </details>)}
    </article>)}</>
}
