"use strict";
function vBench(v){
  const b=S.bench;
  let h=`<div class="card"><div class="row" style="justify-content:space-between"><div><h2 style="margin:0">Benchmark</h2><span class="mut">Runs every built-in scenario and checks the predicted cause.</span></div><button class="btn pri" id="rb">Run benchmark</button></div></div>`;
  if(b)h+=`<div class="card"><div class="row" style="margin-bottom:10px"><span style="font-size:22px;font-weight:600" class="mono">${Math.round(b.accuracy*100)}%</span><span class="mut">${b.passed} of ${b.total} scenarios passed</span></div><div class="wrap"><table><tr><th>Scenario</th><th>Expected</th><th>Predicted</th><th>Confidence</th><th>Result</th></tr>${b.results.map(r=>`<tr><td class="n">${esc(r.scenario)}</td><td class="n mut">${esc(r.expected)}</td><td class="n">${esc(r.predicted)}</td><td class="n">${Math.round(r.confidence*100)}%</td><td><span class="pill ${r.passed?"s-ok":"s-crit"}">${r.passed?"Passed":"Failed"}</span></td></tr>`).join("")}</table></div></div>`;
  v.innerHTML=h;
  $("#rb").onclick=()=>guarded(async()=>{S.bench=await post("/benchmark")});
}
