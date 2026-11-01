"use strict";
function look(res){
  const r=res.report;
  if(r.status==="invalid_input")return{c:"unk",l:"Input rejected",col:"var(--unk)"};
  if(r.status==="insufficient_evidence")return{c:"unk",l:"Insufficient evidence",col:"var(--unk)"};
  if(r.status==="partial")return{c:"warn",l:"Partial diagnosis",col:"var(--warn)"};
  if(r.root_cause_code==="NORMAL")return{c:"ok",l:"Nominal",col:"var(--ok)"};
  return{c:"crit",l:"Root cause identified",col:"var(--crit)"};
}
const chip=a=>`<span class="chip" style="color:${AG[a]||"#94A3B8"};border-color:${AG[a]||"#334155"}55;background:${AG[a]||"#334155"}12">${esc(a)}</span>`;
const fmt=v=>typeof v==="number"?(Math.abs(v)>=100?v.toFixed(0):v.toFixed(2).replace(/\.?0+$/,"")):esc(v);
