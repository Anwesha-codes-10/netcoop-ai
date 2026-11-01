"use strict";
function vMd(v){v.innerHTML=`<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0">Incident report</h2><button class="btn" id="cp">Copy Markdown</button></div><div class="md">${esc(S.res.markdown)}</div></div>`;
  $("#cp").onclick=async e=>{try{await navigator.clipboard.writeText(S.res.markdown);e.target.textContent="Copied"}catch(x){e.target.textContent="Copy failed"}}}
