"use strict";
async function vTopo(v){
  if(!S.topo){v.innerHTML='<div class="empty"><span class="spin"></span>Loading topology…</div>';try{S.topo=await api("/topology")}catch(e){v.innerHTML=`<div class="card err">${esc(e.message)}</div>`;return}}
  if(S.tab!=="topo")return;
  const T=S.topo,aff=new Set((S.res&&S.res.report.affected_devices)||[]);
  const nodes=T.nodes.map(n=>({...n,id:n.device_id||n.id}));
  const types=[...TIERS.filter(t=>nodes.some(n=>n.device_type===t)),...[...new Set(nodes.map(n=>n.device_type))].filter(t=>!TIERS.includes(t))];
  const W=1000,rh=100,H=types.length*rh+30,pos={};
  types.forEach((t,ri)=>{const row=nodes.filter(n=>n.device_type===t);row.forEach((n,i)=>pos[n.id]={x:(i+.5)*W/row.length,y:40+ri*rh,n})});
  const edges=T.edges.map(e=>{const a=pos[e.source],b=pos[e.target];if(!a||!b)return"";const hot=aff.has(e.source)&&aff.has(e.target);return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${hot?"#EF4444":"#334155"}" stroke-width="${hot?2.5:1.2}"><title>${esc(e.source)} to ${esc(e.target)} · ${esc(e.medium)} · ${fmt(e.bandwidth_mbps)} Mbps</title></line>`}).join("");
  const ns=Object.values(pos).map(p=>{const hot=aff.has(p.n.id);return `<g><circle cx="${p.x}" cy="${p.y}" r="${hot?10:7}" fill="${hot?"#EF4444":"#0F172A"}" stroke="${hot?"#FCA5A5":"#38BDF8"}" stroke-width="2"><title>${esc(p.n.id)} · ${esc(p.n.location)} · ${esc(p.n.ip_address)} · ${esc(p.n.model)}</title></circle><text x="${p.x}" y="${p.y+24}" fill="${hot?"#FCA5A5":"#94A3B8"}" font-size="9" text-anchor="middle">${esc(p.n.id)}</text></g>`}).join("");
  v.innerHTML=`<div class="card"><h2>${esc(T.name)} · ${T.node_count} devices, ${T.edge_count} links</h2><div class="wrap"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:900px" role="img" aria-label="Campus topology">${edges}${ns}</svg></div><p class="mut" style="margin:8px 0 0">Rows are device tiers. Hover a device or link for details. Red marks devices in the current diagnosis.</p></div>`;
}
