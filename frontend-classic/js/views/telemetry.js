"use strict";
function vTel(v){
  const T=S.tel;
  if(!T){v.innerHTML='<div class="empty">Telemetry charts are available for scenarios and uploaded telemetry.</div>';return}
  if(!T.valid_json){v.innerHTML=`<div class="card err"><b>This telemetry is not valid JSON</b><p class="mut">Charts need parseable records. Raw text:</p><pre class="sim">${esc(T.raw||"")}</pre></div>`;return}
  const recs=(T.records||[]).filter(r=>r&&typeof r==="object");
  const mv=r=>{const m=r.metrics||r;return m};
  const keys=[...new Set(recs.flatMap(r=>Object.keys(mv(r))))].filter(k=>recs.some(r=>typeof mv(r)[k]==="number"));
  if(!keys.length){v.innerHTML='<div class="empty">No numeric metrics found in these records.</div>';return}
  if(!keys.includes(S.metric))S.metric=keys[0];
  const aff=new Set((S.res&&S.res.report.affected_devices)||[]);
  const by={};recs.forEach(r=>{const d=r.device_id||"unknown";(by[d]=by[d]||[]).push(r)});
  const devs=Object.keys(by);
  const vals=recs.map(r=>mv(r)[S.metric]).filter(x=>typeof x==="number");
  const max=Math.max(...vals,1e-9),W=760,H=240,P=44;
  const maxN=Math.max(...devs.map(d=>by[d].length));
  const ok=["#64748B","#475569","#7C8AA0","#94A3B8"];let oi=0;
  const lines=devs.map(d=>{
    const hot=aff.has(d),col=hot?"#EF4444":ok[oi++%ok.length];
    const pts=by[d].map((r,i)=>{const y=mv(r)[S.metric];return typeof y==="number"?`${P+i*(W-P-12)/Math.max(maxN-1,1)},${H-P/1.4-(y/max)*(H-P*1.4)}`:null}).filter(Boolean).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="${hot?2.2:1.3}" opacity="${hot?1:.8}"/>`}).join("");
  v.innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Metric over time</h2><select id="mt" class="btn mono">${keys.map(k=>`<option ${k===S.metric?"selected":""}>${esc(k)}</option>`).join("")}</select></div>
  <div class="wrap"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:560px;margin-top:10px" role="img" aria-label="${esc(S.metric)} per device">
  ${[0,.5,1].map(f=>`<line x1="${P}" x2="${W-12}" y1="${H-P/1.4-f*(H-P*1.4)}" y2="${H-P/1.4-f*(H-P*1.4)}" stroke="#1E293B"/><text x="${P-6}" y="${H-P/1.4-f*(H-P*1.4)+3}" fill="#94A3B8" font-size="10" text-anchor="end">${fmt(max*f)}</text>`).join("")}${lines}</svg></div>
  <div class="row" style="margin-top:8px">${devs.map(d=>`<span class="tag" style="${aff.has(d)?"color:var(--crit);border-color:#7f1d1d":""}">${esc(d)}</span>`).join("")}</div>
  <p class="mut" style="margin:10px 0 0">Red lines are devices the agents flagged as affected.</p></div>`;
  $("#mt").onchange=e=>{S.metric=e.target.value;render()};
}
