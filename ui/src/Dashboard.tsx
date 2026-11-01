import { useCallback, useEffect, useState } from 'react';
import { Shield, Cpu, AlertTriangle, CheckCircle, Terminal, Activity, FileText, ArrowRight, Play, Loader2 } from 'lucide-react';

/* ---- API types (see docs/API_CONTRACT.md) ---- */
interface Evidence { device_id: string; metric: string; value: number; unit: string; baseline?: number | null; interpretation: string; source_agent: string }
interface Report {
  incident_id: string; status: string; root_cause_code: string; suspected_root_cause: string;
  confidence: number; confidence_category: string; affected_devices: string[];
  supporting_evidence: Evidence[];
  alternative_causes: { cause: string; score: number; why_less_likely: string }[];
  recommended_actions: { priority: number; action: string; rationale: string; requires_human_review?: boolean }[];
  simulated_remediation_preview?: string | null; limitations: string[];
}
interface Msg { index: number; timestamp: string; sender: string; recipient: string; message_type: string; summary: string }
interface Result { report: Report; trace: Msg[]; markdown: string; error?: { code: string; detail: string } | null }
interface Row { incident_id: string; status: string; root_cause_code?: string; confidence?: number }
interface Scenario { name: string; description: string }

const AGENTS: Record<string, string> = {
  orchestrator: '#F8FAFC', telemetry_agent: '#06B6D4', infrastructure_agent: '#10B981',
  connectivity_agent: '#F59E0B', correlation_agent: '#A855F7', reporting_agent: '#38BDF8',
};
const col = (a: string) => AGENTS[a] ?? '#94A3B8';

async function api<T>(path: string, opt?: RequestInit): Promise<T> {
  let r: Response;
  try { r = await fetch('/api' + path, opt); } catch { throw new Error('Cannot reach the NetCoop server. Start it with: netcoop serve'); }
  const body = (r.headers.get('content-type') || '').includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`);
  return body as T;
}

/* Status colours: nominal green, fault red, partial yellow, unknown slate */
function look(r: Report) {
  if (r.status === 'invalid_input') return { label: 'Input rejected', cls: 'text-slate-400 border-slate-700 bg-slate-900', bar: '#64748B' };
  if (r.status === 'insufficient_evidence') return { label: 'Insufficient evidence', cls: 'text-slate-400 border-slate-700 bg-slate-900', bar: '#64748B' };
  if (r.status === 'partial') return { label: 'Partial diagnosis', cls: 'text-yellow-400 border-yellow-900/60 bg-yellow-950/40', bar: '#EAB308' };
  if (r.root_cause_code === 'NORMAL') return { label: 'Nominal', cls: 'text-emerald-400 border-emerald-800/60 bg-emerald-950/40', bar: '#22C55E' };
  return { label: 'Root cause identified', cls: 'text-red-400 border-red-900/60 bg-red-950/40', bar: '#EF4444' };
}

export default function Dashboard() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [pick, setPick] = useState('link_congestion');
  const [rows, setRows] = useState<Row[]>([]);
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRows = useCallback(() => {
    api<Row[]>('/incidents').then(setRows).catch(() => undefined);
  }, []);

  useEffect(() => {
    api<{ version: string }>('/health').then(() => setOnline(true)).catch((e: Error) => { setOnline(false); setError(e.message); });
    api<Scenario[]>('/scenarios').then(setScenarios).catch(() => undefined);
    loadRows();
  }, [loadRows]);

  const guarded = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); }
    setBusy(false); loadRows();
  };

  const run = () => guarded(async () => {
    setRes(await api<Result>('/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario: pick }) }));
  });

  const open = (id: string) => guarded(async () => {
    const [report, trace, markdown] = await Promise.all([
      api<Report>(`/incidents/${id}/report.json`), api<Msg[]>(`/incidents/${id}/trace`), api<string>(`/incidents/${id}/report.md`),
    ]);
    setRes({ report, trace, markdown, error: null });
  });

  const r = res?.report;
  const L = r ? look(r) : null;
  const seen = new Set((res?.trace ?? []).map((m) => m.sender));
  const lastSender = res?.trace.length ? res.trace[res.trace.length - 1].sender : '';

  return (
    <div className="min-h-screen bg-[#080C14] text-slate-100 font-sans antialiased selection:bg-cyan-500/30">
      <header className="border-b border-slate-800 bg-slate-900/60 px-6 py-4 flex flex-wrap gap-3 items-center justify-between backdrop-blur-sm sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="bg-cyan-600 p-2 rounded-xl text-white shadow-lg shadow-cyan-600/20"><Shield className="w-6 h-6" /></div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">NetCoop AI</h1>
            <p className="text-xs text-slate-400">Multi-agent network fault diagnosis · IIT Bhubaneswar campus</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Scenario"
            className="bg-slate-900 border border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono">
            {scenarios.map((s) => <option key={s.name} value={s.name} title={s.description}>{s.name}</option>)}
          </select>
          <button onClick={run} disabled={busy || !online}
            className="flex items-center gap-2 text-xs bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 transition-colors border border-cyan-500/60 px-3 py-1.5 rounded-xl font-semibold">
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5 fill-current" />} Run diagnosis
          </button>
          <div className={`flex items-center gap-2 text-xs border px-3 py-1.5 rounded-xl ${online ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/60' : 'bg-red-950/40 text-red-400 border-red-900/60'}`}>
            <span className={`w-2 h-2 rounded-full ${online ? 'bg-emerald-400' : 'bg-red-400'}`} />
            {online === null ? 'Connecting…' : online ? 'API online' : 'API offline'}
          </div>
        </div>
      </header>

      <section className="grid grid-cols-1 md:grid-cols-4 gap-4 p-6">
        <Stat icon={<Activity className="text-cyan-500 w-8 h-8" />} label="Orchestrator" value={online ? 'Online' : 'Offline'} />
        <Stat icon={<Cpu className="text-purple-500 w-8 h-8" />} label="Agents in this diagnosis" value={r ? `${seen.size} of 6` : '–'} />
        <Stat icon={<AlertTriangle className="text-amber-500 w-8 h-8" />} label="Saved incidents" value={String(rows.length)} />
        <Stat icon={<CheckCircle className="text-emerald-500 w-8 h-8" />} label="Confidence" value={r ? `${Math.round(r.confidence * 100)}% (${r.confidence_category})` : '–'} />
      </section>

      {error && <div role="alert" className="mx-6 p-4 bg-red-950/40 border border-red-900 text-red-400 text-sm rounded-xl"><strong>Something went wrong:</strong> {error}</div>}

      <main className="grid grid-cols-1 lg:grid-cols-3 gap-6 p-6">
        <div className="lg:col-span-1 bg-slate-900/40 border border-slate-800 rounded-2xl p-4 flex flex-col max-h-[75vh]">
          <h2 className="text-xs font-bold tracking-wider text-slate-400 uppercase mb-4">Saved incidents</h2>
          {rows.length === 0 ? (
            <div className="text-sm text-slate-500 font-mono text-center px-4 py-10">No incidents yet. Pick a scenario and press Run diagnosis.</div>
          ) : (
            <div className="space-y-3 overflow-y-auto pr-1">
              {rows.map((i) => (
                <button key={i.incident_id} onClick={() => open(i.incident_id)}
                  className={`w-full text-left p-4 rounded-xl border transition-all ${r?.incident_id === i.incident_id ? 'bg-cyan-950/20 border-cyan-500/60' : 'bg-slate-900/40 border-slate-800 hover:border-slate-600'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-mono font-bold text-cyan-400">{i.incident_id}</span>
                    <span className="text-[10px] font-mono text-slate-400">{i.confidence != null ? Math.round(i.confidence * 100) + '%' : '–'}</span>
                  </div>
                  <div className="text-sm text-slate-200 font-mono">{i.root_cause_code ?? i.status}</div>
                  <div className="text-xs text-slate-500">{i.status}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 flex flex-col gap-6">
          {!r || !L ? (
            <div className="bg-slate-900/20 border border-dashed border-slate-800 rounded-2xl flex items-center justify-center text-sm text-slate-500 font-mono min-h-[300px] text-center px-6">
              {busy ? 'Agents are analysing the telemetry…' : 'Run a scenario or open a saved incident to see the agents’ diagnosis.'}
            </div>
          ) : (<>
            {res?.error && <div className="p-4 bg-red-950/40 border border-red-900 text-red-300 text-sm rounded-xl"><strong>{res.error.code}</strong>: {res.error.detail}</div>}

            <Panel title="Verdict">
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className={`text-xs px-3 py-0.5 rounded-full border font-semibold ${L.cls}`}>{L.label}</span>
                <span className="text-xs font-mono text-slate-400">{r.incident_id} · {r.root_cause_code}</span>
              </div>
              <h3 className="text-xl font-semibold mb-3">{r.suspected_root_cause}</h3>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden max-w-sm"><div className="h-full" style={{ width: `${Math.round(r.confidence * 100)}%`, background: L.bar }} /></div>
              {r.affected_devices.length > 0 && <div className="flex flex-wrap gap-2 mt-3">{r.affected_devices.map((d) => <span key={d} className="text-xs font-mono text-red-400 border border-red-900/60 rounded px-2 py-0.5">{d}</span>)}</div>}
            </Panel>

            <Panel title="Multi-agent pipeline">
              <div className="flex items-center gap-3 text-xs font-mono bg-slate-950/60 p-3 rounded-xl border border-slate-800 overflow-x-auto">
                {Object.keys(AGENTS).map((a, idx, arr) => (
                  <span key={a} className="flex items-center gap-3 shrink-0">
                    <span className="flex items-center gap-2 px-3 py-2 rounded-lg border" style={seen.has(a) ? { color: col(a), borderColor: col(a) + '99', background: col(a) + '14', fontWeight: 700 } : { color: '#64748B', borderColor: '#1E293B' }}>
                      <span className={`w-2 h-2 rounded-full ${a === lastSender ? 'animate-pulse' : ''}`} style={{ background: seen.has(a) ? col(a) : '#334155' }} />{a}
                    </span>
                    {idx < arr.length - 1 && <ArrowRight className="w-4 h-4 text-slate-700" />}
                  </span>
                ))}
              </div>
            </Panel>

            <Panel title="Agent messages" icon={<Terminal className="w-4 h-4 text-cyan-400" />}>
              {res!.trace.length === 0 ? <p className="text-xs text-slate-500 font-mono">No agent messages. The input was rejected before analysis.</p> : (
                <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 font-mono text-xs space-y-2 max-h-72 overflow-y-auto">
                  {res!.trace.map((m) => (
                    <div key={m.index} className="p-2 rounded-lg border border-slate-900 bg-slate-900/20">
                      <span className="text-slate-500">{m.index}. </span>
                      <span style={{ color: col(m.sender) }} className="font-bold">{m.sender}</span>
                      <span className="text-slate-500"> to </span>
                      <span style={{ color: col(m.recipient) }} className="font-bold">{m.recipient}</span>
                      <span className="text-slate-500"> · {m.message_type}</span>
                      <div className="text-slate-400">{m.summary.split(' | ').slice(2).join(' | ')}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Supporting evidence">
              {r.supporting_evidence.length === 0 ? <p className="text-xs text-slate-500 font-mono">No evidence was asserted for this incident.</p> : (
                <div className="overflow-x-auto"><table className="w-full text-xs font-mono">
                  <thead><tr className="text-slate-500 text-left"><th className="py-1 pr-3">Device</th><th className="pr-3">Metric</th><th className="pr-3">Value</th><th className="pr-3">Baseline</th><th className="pr-3">Reading</th><th>Source</th></tr></thead>
                  <tbody>{r.supporting_evidence.map((e, i) => (
                    <tr key={i} className="border-t border-slate-800 align-top">
                      <td className="py-1.5 pr-3">{e.device_id}</td><td className="pr-3">{e.metric}</td>
                      <td className="pr-3 whitespace-nowrap">{e.value} {e.unit}</td><td className="pr-3 text-slate-500">{e.baseline ?? '–'}</td>
                      <td className="pr-3 font-sans text-slate-300">{e.interpretation}</td><td style={{ color: col(e.source_agent) }}>{e.source_agent}</td>
                    </tr>))}</tbody>
                </table></div>
              )}
            </Panel>

            <div className="grid md:grid-cols-2 gap-6">
              <Panel title="Recommended actions">
                {r.recommended_actions.map((a, i) => (
                  <div key={i} className="flex gap-3 py-2 border-b border-slate-800 last:border-0 text-sm">
                    <span className="font-mono text-sky-400 text-xs">P{a.priority}</span>
                    <div><div>{a.action}</div><div className="text-xs text-slate-400">{a.rationale}</div>
                      {a.requires_human_review && <span className="text-[10px] text-yellow-400 border border-yellow-900/60 rounded-full px-2">Needs human review</span>}</div>
                  </div>))}
                {r.simulated_remediation_preview && <pre className="mt-3 text-xs font-mono text-sky-300 bg-slate-950 border border-dashed border-slate-700 rounded-lg p-3 whitespace-pre-wrap">{r.simulated_remediation_preview}</pre>}
              </Panel>
              <Panel title="Alternative causes and limits">
                {r.alternative_causes.map((a) => (
                  <div key={a.cause} className="mb-2 text-xs"><div className="flex justify-between font-mono"><span>{a.cause}</span><span className="text-slate-400">{Math.round(a.score * 100)}%</span></div><div className="text-slate-400">{a.why_less_likely}</div></div>))}
                <ul className="list-disc pl-4 text-xs text-slate-400 mt-2">{r.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </Panel>
            </div>

            <Panel title="Incident report (Markdown)" icon={<FileText className="w-4 h-4 text-purple-400" />}>
              <pre className="bg-slate-950/80 p-4 rounded-xl border border-slate-800 font-mono text-xs text-slate-300 whitespace-pre-wrap max-h-60 overflow-y-auto">{res!.markdown}</pre>
            </Panel>
          </>)}
        </div>
      </main>
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl flex items-center gap-4">
      {icon}<div><p className="text-xs text-slate-400 font-medium">{label}</p><h3 className="text-lg font-semibold">{value}</h3></div>
    </div>
  );
}
function Panel({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-4">
      <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">{icon}{title}</h2>
      {children}
    </div>
  );
}
