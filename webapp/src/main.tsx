import './styles.css'
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AtlasGraph } from './atlas/AtlasGraph'
import { ArrowLeft, ArrowUpRight, BookOpen, Check, Download, GitBranch, LoaderCircle, Network, Search, Sparkles, Trash2 } from 'lucide-react'

export type Paper = { id: string; title: string; year: number | null; authors?: string[]; doi?: string | null; abstract?: string | null; cited_by_count?: number; document_type?: string | null; topics?: string[]; referenced_works?: string[] }
type Edge = { source: string; target: string; type: string; evidence_status?: string; route_support?: boolean; display_weight?: number; evidence_weight?: number }
type Candidate = { roles: string[]; selection_reasons: string[]; relevance_score?: number; semantic_score?: number; influence_score?: number; bridge_score?: number; route_score?: number; shared_reference_count?: number; citation_edges?: { source: string; target: string }[] }
export type Result = { seeds: string[]; papers: Record<string, Paper>; edges: Edge[]; routes: { id?: string; paper_ids: string[]; score: number; evidence_status: string; explanation: string }[]; reading_list: { paper_id: string; tier: string; reason: string; evidence_status: string }[]; candidates: Record<string, Candidate>; provenance?: Record<string, any>; warnings?: string[]; feedback?: { paper_id: string; state: string; note?: string }[] }
type SearchHistory = { graph_id: string; job_id: string; seeds: string[]; seed_titles: string[]; paper_count: number; created_at: string }

const API = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

function App() {
  const [seedText, setSeedText] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<any>(null)
  const [graph, setGraph] = useState<Result | null>(null)
  const [history, setHistory] = useState<SearchHistory[]>([])
  const [historySelection, setHistorySelection] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const refreshHistory = async () => {
    try {
      const response = await fetch(`${API}/api/v1/searches`)
      if (!response.ok) return
      setHistory(await response.json())
    } catch {
      // History is a convenience; a backend outage should not block a new search.
    }
  }

  useEffect(() => { void refreshHistory() }, [])

  useEffect(() => {
    if (!jobId) return
    const started = Date.now()
    const timer = window.setInterval(async () => {
      if (Date.now() - started > 10 * 60 * 1000) {
        setError('This build exceeded the 10-minute limit. Start a new search or inspect the backend logs.')
        window.clearInterval(timer)
        return
      }
      try {
        const response = await fetch(`${API}/api/v1/jobs/${jobId}`)
        if (!response.ok) throw new Error(`Job status HTTP ${response.status}`)
        const data = await response.json()
        setJob(data)
        if (data.status === 'completed' && data.graph_id) {
          const graphResponse = await fetch(`${API}/api/v1/graphs/${data.graph_id}`)
          if (!graphResponse.ok) throw new Error(`Graph HTTP ${graphResponse.status}`)
          const graphData = await graphResponse.json()
          setGraph(graphData)
          setSelected(graphData.seeds[0] ?? null)
          void refreshHistory()
          window.clearInterval(timer)
        }
        if (data.status === 'failed') {
          setError(data.error ?? 'The build failed')
          window.clearInterval(timer)
        }
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : 'The build status could not be loaded')
        window.clearInterval(timer)
      }
    }, 700)
    return () => window.clearInterval(timer)
  }, [jobId])

  const submit = async () => {
    const seeds = seedText.split(/\n|,/).map((value) => value.trim()).filter(Boolean).slice(0, 3)
    if (!seeds.length) return
    setError(null); setGraph(null); setHistorySelection(''); setJob({ status: 'queued', progress: 'queued' })
    let response: Response
    try {
      response = await fetch(`${API}/api/v1/jobs`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ seeds }) })
    } catch {
      setError('Cannot reach the local backend. Start the API on port 8000 and try again.')
      return
    }
    if (!response.ok) { setError(await response.text()); return }
    const data = await response.json(); setJobId(data.job_id)
  }

  const openHistory = async (graphId: string) => {
    if (!graphId) return
    setError(null)
    try {
      const response = await fetch(`${API}/api/v1/graphs/${encodeURIComponent(graphId)}`)
      if (!response.ok) throw new Error(`Saved search HTTP ${response.status}`)
      const data = await response.json()
      setGraph(data); setSelected(data.seeds[0] ?? null); setJobId(null); setJob(null)
    } catch (historyError) {
      setError(historyError instanceof Error ? historyError.message : 'Could not load saved search')
    }
  }

  const deleteHistory = async () => {
    if (!historySelection) return
    const graphId = historySelection
    const response = await fetch(`${API}/api/v1/searches/${encodeURIComponent(graphId)}`, { method: 'DELETE' })
    if (!response.ok) {
      setError('Could not delete the saved search')
      return
    }
    setHistory((current) => current.filter((item) => item.graph_id !== graphId))
    setHistorySelection('')
  }

  const updateFeedback = async (paperId: string, state: string) => {
    if (!graph) return
    setFeedback((current) => ({ ...current, [paperId]: state }))
    await fetch(`${API}/api/v1/graphs/${encodeURIComponent(graph.provenance?.graph_id ?? '')}/papers/${encodeURIComponent(paperId)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ state }) }).catch(() => undefined)
  }

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><Network size={18} /></div><div><strong>PaperNexus</strong><span>Evidence atlas</span></div></div><div className="topbar-meta">{graph ? `${Object.keys(graph.papers).length} papers · weighted field` : 'Local alpha'}</div></header>
    {!graph ? <Landing seedText={seedText} setSeedText={setSeedText} submit={submit} job={job} error={error} history={history} historySelection={historySelection} setHistorySelection={setHistorySelection} onOpenHistory={openHistory} onDeleteHistory={deleteHistory} /> : <Workspace graph={graph} selected={selected} setSelected={setSelected} feedback={feedback} updateFeedback={updateFeedback} onBack={() => { setGraph(null); setJobId(null); setJob(null); setError(null); setFeedback({}); setSelected(null); void refreshHistory() }} />}
  </div>
}

function Landing({ seedText, setSeedText, submit, job, error, history, historySelection, setHistorySelection, onOpenHistory, onDeleteHistory }: { seedText: string; setSeedText: (value: string) => void; submit: () => void; job: any; error: string | null; history: SearchHistory[]; historySelection: string; setHistorySelection: (value: string) => void; onOpenHistory: (graphId: string) => void; onDeleteHistory: () => void }) {
  return <main className="landing"><section className="landing-copy"><div className="eyebrow"><Sparkles size={14} /> Research atlas builder</div><h1>See how a field got here.</h1><p>Start with one to three papers. PaperNexus traces cited foundations, later work, and related branches with evidence attached to every connection.</p><div className="seed-form"><label htmlFor="seeds">Seed papers</label><textarea id="seeds" value={seedText} onChange={(event) => setSeedText(event.target.value)} placeholder="DOI, OpenAlex ID, arXiv ID, or title\nOne paper per line" rows={4} /><button className="primary" onClick={submit}><Search size={17} /> Build atlas</button></div><div className="history-picker"><label htmlFor="saved-searches">Previous searches</label><div className="history-row"><select id="saved-searches" value={historySelection} onChange={(event) => { setHistorySelection(event.target.value); onOpenHistory(event.target.value) }} disabled={!history.length}><option value="">{history.length ? 'Choose a saved search' : 'No saved searches yet'}</option>{history.map((item) => { const label = item.seed_titles.length ? item.seed_titles.join(' · ') : item.seeds.join(' · '); const when = new Date(item.created_at).toLocaleString(); return <option key={item.graph_id} value={item.graph_id}>{label.slice(0, 82)} · {item.paper_count} papers · {when}</option> })}</select><button className="icon-action" title="Delete selected search" aria-label="Delete selected search" disabled={!historySelection} onClick={onDeleteHistory}><Trash2 size={16} /></button></div></div>{job && <div className="job-status"><LoaderCircle size={16} className="spin" /><span>{job.progress ?? job.status}</span></div>}{error && <div className="error">{error}</div>}</section><aside className="landing-aside"><div className="signal-card"><div className="signal-icon"><GitBranch size={19} /></div><strong>Traceable by design</strong><span>Confirmed citations form the strongest connections. Similarity and co-citation remain visible as discovery signals.</span></div><div className="signal-card"><div className="signal-icon amber"><BookOpen size={19} /></div><strong>Reading order included</strong><span>Get a short list of what to read first and why each paper is present.</span></div></aside></main>
}

function Workspace({ graph, selected, setSelected, feedback, updateFeedback, onBack }: { graph: Result; selected: string | null; setSelected: (id: string) => void; feedback: Record<string, string>; updateFeedback: (id: string, state: string) => void; onBack: () => void }) {
  const selectedPaper = selected ? graph.papers[selected] : null
  const reading = graph.reading_list ?? []
  return <main className="workspace"><div className="workspace-head"><div><div className="eyebrow">Atlas ready</div><h1>Research evolution</h1><p>{graph.warnings?.[0] ?? 'A weighted, evidence-aware view of the sampled literature.'}</p></div><div className="workspace-actions"><button className="quiet-action" onClick={onBack}><ArrowLeft size={15} /> New search</button><div className="export-actions"><a href={`${API}/api/v1/graphs/${encodeURIComponent(graph.provenance?.graph_id ?? '')}/export?format=bibtex`}><Download size={15} /> BibTeX</a><a href={`${API}/api/v1/graphs/${encodeURIComponent(graph.provenance?.graph_id ?? '')}/export?format=json`}><Download size={15} /> JSON</a></div></div></div><div className="mode-note">Follow the bright arrows to trace citations. Scroll to focus and expand or collapse papers. A citation does not prove intellectual inheritance.</div><div className="work-grid"><section className="graph-panel"><AtlasGraph graph={graph} selected={selected} setSelected={setSelected} /></section><aside className="side-panel">{selectedPaper ? <EvidenceDrawer paper={selectedPaper} graph={graph} feedback={feedback[selectedPaper.id]} updateFeedback={updateFeedback} /> : <div className="empty-state">Select a paper to inspect its evidence.</div>}<ReadingList graph={graph} reading={reading} selected={selected} setSelected={setSelected} /></aside></div></main>
}

function EvidenceDrawer({ paper, graph, feedback, updateFeedback }: { paper: Paper; graph: Result; feedback?: string; updateFeedback: (id: string, state: string) => void }) {
  const evidence = graph.candidates?.[paper.id]
  return <div className="evidence"><div className="panel-kicker">Paper evidence</div><h2>{paper.title}</h2><div className="paper-meta">{paper.year ?? 'Year unknown'} · {paper.cited_by_count ?? 0} citations</div><p className="authors">{paper.authors?.slice(0, 4).join(', ')}</p>{paper.abstract && <p className="abstract">{paper.abstract.slice(0, 460)}{paper.abstract.length > 460 ? '…' : ''}</p>}<div className="chips">{(evidence?.roles ?? []).map((role) => <span key={role}>{role.replace('_', ' ')}</span>)}</div><div className="evidence-metrics"><span>relevance {Math.round((evidence?.relevance_score ?? 0) * 100)}%</span><span>semantic {Math.round((evidence?.semantic_score ?? 0) * 100)}%</span><span>route {Math.round((evidence?.route_score ?? 0) * 100)}%</span><span>{evidence?.citation_edges?.length ?? 0} citation edges</span></div><div className="evidence-reasons">{(evidence?.selection_reasons ?? ['Connected to the sampled graph']).map((reason) => <div key={reason}><Check size={14} /> {reason}</div>)}</div><div className="paper-actions"><button className={feedback === 'reading' ? 'selected-action' : ''} onClick={() => updateFeedback(paper.id, 'reading')}><BookOpen size={15} /> Read next</button><button className={feedback === 'relevant' ? 'selected-action' : ''} onClick={() => updateFeedback(paper.id, 'relevant')}><Check size={15} /> Relevant</button><a href={paper.doi ? `https://doi.org/${paper.doi.replace(/^https?:\/\/doi.org\//, '')}` : `https://openalex.org/${paper.id}`} target="_blank" rel="noreferrer"><ArrowUpRight size={15} /> Source</a></div></div>
}

function ReadingList({ graph, reading, selected, setSelected }: { graph: Result; reading: Result['reading_list']; selected: string | null; setSelected: (id: string) => void }) {
  return <div className="reading"><div className="reading-head"><div><div className="panel-kicker">Priority reading</div><h2>Start here</h2></div><span>{reading.length} papers</span></div>{reading.slice(0, 10).map((item) => { const paper = graph.papers[item.paper_id]; if (!paper) return null; return <button key={item.paper_id} className={`reading-item ${selected === paper.id ? 'selected-reading' : ''}`} onClick={() => setSelected(paper.id)}><span className="tier">{item.tier}</span><strong>{paper.title}</strong><small>{item.reason}</small></button> })}</div>
}

export default App

createRoot(document.getElementById('root')!).render(<App />)
