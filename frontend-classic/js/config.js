"use strict";
const AG={orchestrator:"#F8FAFC",telemetry_agent:"#06B6D4",infrastructure_agent:"#10B981",connectivity_agent:"#F59E0B",correlation_agent:"#A855F7",reporting_agent:"#38BDF8"};
const AG_ROLE={orchestrator:"Coordination",telemetry_agent:"Latency, loss, throughput",infrastructure_agent:"CPU, memory, queue drops",connectivity_agent:"Topology and routing",correlation_agent:"Rules and consensus",reporting_agent:"Recommendations"};
const TABS=[["diag","Diagnosis"],["trace","Agent trace"],["tel","Telemetry"],["topo","Topology"],["md","Report"],["bench","Benchmark"]];
const TIERS=["gateway","core_router","distribution_switch","access_switch","access_point"];
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const S={tab:"diag",res:null,tel:null,topo:null,scen:[],sel:null,busy:false,bench:null,metric:"latency_ms",err:null};
