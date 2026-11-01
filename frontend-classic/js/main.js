"use strict";
/* ---------- boot ---------- */
(async()=>{
  render();
  try{const h=await api("/health");$("#hs").innerHTML=`<i class="dot on"></i>API online · v${esc(h.version)}`}
  catch(e){$("#hs").innerHTML='<i class="dot off"></i>API offline';S.err=e.message;render();return}
  try{S.scen=await api("/scenarios");drawScen()}catch(e){$("#scs").textContent=e.message}
  loadIncidents();
})();
