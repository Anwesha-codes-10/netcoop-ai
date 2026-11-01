"use strict";
/* ---------- views ---------- */
function tabs(){
  $("#tabs").innerHTML=TABS.map(([k,l])=>`<button role="tab" class="${S.tab===k?"on":""}" data-k="${k}">${l}</button>`).join("");
  $("#tabs").querySelectorAll("button").forEach(b=>b.onclick=()=>{S.tab=b.dataset.k;render()});
}
function render(){
  tabs();
  const v=$("#view");
  document.querySelectorAll(".btn,.sc").forEach(b=>b.disabled=S.busy);
  if(S.busy){v.innerHTML='<div class="empty"><span class="spin"></span>Agents are analysing the telemetry…</div>';return}
  if(S.err){v.innerHTML=`<div class="card err"><b>Something went wrong</b><p>${esc(S.err)}</p></div>`;return}
  if(S.tab==="bench")return vBench(v);
  if(S.tab==="topo")return vTopo(v);
  if(!S.res){v.innerHTML='<div class="empty"><h3 style="color:var(--txt);margin:0 0 6px">No diagnosis yet</h3>Pick a scenario on the left, or upload telemetry, to start a multi-agent diagnosis.</div>';return}
  ({diag:vDiag,trace:vTrace,tel:vTel,md:vMd}[S.tab])(v);
}
