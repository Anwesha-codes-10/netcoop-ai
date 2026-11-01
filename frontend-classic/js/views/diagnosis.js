"use strict";
function vDiag(v){
  const res=S.res,r=res.report,L=look(res),conf=Math.round((r.confidence||0)*100);
  const st=r.agent_status||{};
  const names=Object.keys(AG).filter(a=>a==="orchestrator"||a in st||(res.trace||[]).some(t=>t.sender===a));
  const cnt=a=>(res.trace||[]).filter(t=>t.sender===a).length;
  let h=`<div class="pipe">${names.map(a=>`<div class="node" style="border-color:${AG[a]}66;background:${AG[a]}0d"><b style="color:${AG[a]}">${a}</b><span>${AG_ROLE[a]}</span><br><span class="mono">${a==="orchestrator"?"":esc(st[a]||"")+" · "}${cnt(a)} msg</span></div>`).join("")}</div>`;
  if(res.error)h+=`<div class="card err"><b>Telemetry rejected: ${esc(res.error.code)}</b><p>${esc(res.error.detail)}</p>${res.error.line?`<p class="mono mut">line ${res.error.line}, column ${res.error.column}</p>`:""}</div>`;
  h+=`<div class="card verdict" style="border-left-color:${L.col}">
    <div class="row"><span class="pill s-${L.c}">${L.l}</span><span class="mono mut">${esc(r.incident_id)}</span><span class="tag">${esc(r.status)}</span></div>
    <h3>${esc(r.suspected_root_cause)}</h3>
    <div class="row mut"><span class="mono">${esc(r.root_cause_code)}</span></div>
    <div style="margin-top:12px;max-width:420px"><div class="row" style="justify-content:space-between"><span class="mut">Confidence (${esc(r.confidence_category)})</span><span class="mono">${conf}%</span></div><div class="bar"><i style="width:${conf}%;background:${L.col}"></i></div></div>
    ${(r.affected_devices||[]).length?`<p style="margin:14px 0 4px" class="mut">Affected devices</p><div class="row">${r.affected_devices.map(d=>`<span class="tag" style="color:var(--crit);border-color:#7f1d1d">${esc(d)}</span>`).join("")}${(r.affected_segments||[]).map(d=>`<span class="tag">${esc(d)}</span>`).join("")}</div>`:""}
  </div>`;
  h+=`<div class="card"><h2>Supporting evidence</h2>${(r.supporting_evidence||[]).length?`<div class="wrap"><table><tr><th>Device</th><th>Metric</th><th>Value</th><th>Baseline</th><th>Reading</th><th>Source</th></tr>${r.supporting_evidence.map(e=>`<tr><td class="n">${esc(e.device_id)}</td><td class="n">${esc(e.metric)}</td><td class="n">${fmt(e.value)} ${esc(e.unit)}</td><td class="n mut">${e.baseline!=null?fmt(e.baseline):"–"}</td><td>${esc(e.interpretation)}</td><td>${chip(e.source_agent)}</td></tr>`).join("")}</table></div>`:'<span class="mut">No evidence was asserted for this incident.</span>'}</div>`;
  h+=`<div class="grid2"><div class="card"><h2>Recommended actions</h2>${(r.recommended_actions||[]).map(a=>`<div class="act"><span class="pn">P${a.priority}</span><div><div>${esc(a.action)}</div><div class="mut" style="font-size:12px">${esc(a.rationale)}</div>${a.requires_human_review?'<span class="pill s-warn" style="font-size:11px">Needs human review</span>':""}</div></div>`).join("")||'<span class="mut">None</span>'}
    ${r.simulated_remediation_preview?`<h2 style="margin-top:14px">Simulated remediation</h2><div class="sim">${esc(r.simulated_remediation_preview)}</div>`:""}</div>
    <div class="card"><h2>Alternative causes</h2>${(r.alternative_causes||[]).map(a=>`<div style="margin-bottom:10px"><div class="row" style="justify-content:space-between"><span class="mono">${esc(a.cause)}</span><span class="mono mut">${Math.round(a.score*100)}%</span></div><div class="bar"><i style="width:${Math.round(a.score*100)}%;background:#A855F7"></i></div><div class="mut" style="font-size:12px;margin-top:2px">${esc(a.why_less_likely)}</div></div>`).join("")||'<span class="mut">None considered</span>'}
    ${(r.conflicts_resolved||[]).length?`<h2 style="margin-top:14px">Conflicts resolved</h2><ul style="margin:0;padding-left:18px">${r.conflicts_resolved.map(c=>`<li>${esc(typeof c==="string"?c:JSON.stringify(c))}</li>`).join("")}</ul>`:""}</div></div>`;
  const dq=r.data_quality||{};
  h+=`<div class="grid2"><div class="card"><h2>Data quality</h2><div class="row" style="justify-content:space-between"><span class="mut">Completeness</span><span class="mono">${Math.round((dq.completeness||0)*100)}%</span></div><div class="bar"><i style="width:${Math.round((dq.completeness||0)*100)}%;background:var(--ok)"></i></div>
    <p class="mut" style="margin:10px 0 0">${(r.normalization_log||[]).length} normalisation steps · ${(dq.missing_fields||[]).length} missing fields · ${(dq.stale_fields||[]).length} stale fields</p>
    ${(dq.assumptions||[]).map(a=>`<p class="mut" style="margin:6px 0 0">${esc(a)}</p>`).join("")}</div>
    <div class="card"><h2>Limitations</h2><ul style="margin:0;padding-left:18px">${(r.limitations||[]).map(l=>`<li>${esc(l)}</li>`).join("")}</ul></div></div>`;
  v.innerHTML=h;
}
