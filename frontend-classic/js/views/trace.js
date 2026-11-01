"use strict";
function vTrace(v){
  const t=S.res.trace||[];
  if(!t.length){v.innerHTML='<div class="empty">No agent messages were recorded. The input was rejected before analysis.</div>';return}
  v.innerHTML=`<div class="card"><h2>${t.length} messages between agents</h2>${t.map(m=>{
    const p=JSON.stringify(m.payload,null,2)||"";
    const time=(m.timestamp||"").slice(11,23);
    return `<details><summary><span class="mono mut" style="min-width:24px">${m.index}</span><span class="mono mut">${esc(time)}</span>${chip(m.sender)}<span class="mut">to</span>${chip(m.recipient)}<span class="tag">${esc(m.message_type)}</span><span style="flex-basis:100%;color:var(--mut);font-size:12px;padding-left:32px">${esc((m.summary||"").split(" | ").slice(2).join(" | "))}</span></summary><pre>${esc(p.length>8000?p.slice(0,8000)+"\n… truncated":p)}</pre></details>`}).join("")}</div>`;
}
