"use strict";
async function api(path,opt){
  let r;
  try{r=await fetch("/api"+path,opt)}catch(e){throw new Error("Can’t reach the NetCoop server. Start it with netcoop serve.")}
  const ct=r.headers.get("content-type")||"";
  const body=ct.includes("json")?await r.json():await r.text();
  if(!r.ok)throw new Error(body&&body.detail?body.detail:"Request failed ("+r.status+")");
  return body;
}
const post=(p,b)=>api(p,{method:"POST",headers:{"Content-Type":"application/json"},body:b===undefined?undefined:JSON.stringify(b)});
