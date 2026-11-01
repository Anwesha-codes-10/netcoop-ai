"use strict";
/* ---------- sidebar ---------- */
function drawScen(){
  $("#scs").innerHTML=S.scen.map(s=>`<button class="sc${S.sel===s.name?" sel":""}" data-n="${esc(s.name)}"><span class="mono">${esc(s.name)}</span><small>${esc(s.description)}</small></button>`).join("");
  $("#scs").querySelectorAll("button").forEach(b=>b.onclick=()=>runScenario(b.dataset.n));
}
async function loadIncidents(){
  try{
    const l=await api("/incidents");
    $("#incs").innerHTML=l.length?l.slice(0,12).map(i=>`<button class="sc" data-i="${esc(i.incident_id)}"><span class="mono">${esc(i.incident_id)}</span> <span class="tag">${esc(i.root_cause_code||i.status)}</span><small>${esc(i.status)} · ${i.confidence!=null?Math.round(i.confidence*100)+"%":"–"}</small></button>`).join(""):'<span class="mut">None yet. Run a scenario to create one.</span>';
    $("#incs").querySelectorAll("button").forEach(b=>b.onclick=()=>openIncident(b.dataset.i));
  }catch(e){}
}

/* ---------- actions ---------- */
async function guarded(fn){
  if(S.busy)return;S.busy=true;S.err=null;render();
  try{await fn()}catch(e){S.err=e.message}
  S.busy=false;render();loadIncidents();
}
const runScenario=n=>guarded(async()=>{
  S.sel=n;drawScen();S.tab="diag";
  S.res=await post("/diagnose",{scenario:n});
  try{S.tel=await api("/scenarios/"+encodeURIComponent(n)+"/telemetry")}catch(e){S.tel=null}
});
const runText=t=>guarded(async()=>{
  S.sel=null;drawScen();S.tab="diag";
  if(!t.trim())throw new Error("Add telemetry first: choose a JSON file or paste JSON.");
  S.res=await post("/diagnose",{telemetry:t});
  try{const j=JSON.parse(t);S.tel={valid_json:true,records:Array.isArray(j)?j:[j]}}catch(e){S.tel={valid_json:false,records:null,raw:t}}
});
const openIncident=id=>guarded(async()=>{
  S.sel=null;drawScen();S.tab="diag";S.tel=null;
  const [report,trace,md]=await Promise.all([api(`/incidents/${id}/report.json`),api(`/incidents/${id}/trace`),api(`/incidents/${id}/report.md`)]);
  S.res={report,trace,markdown:md,error:null};
});
$("#file").onchange=e=>{const f=e.target.files[0];if(f)f.text().then(t=>{$("#paste").value=t;runText(t)})};
$("#runPaste").onclick=()=>runText($("#paste").value);
