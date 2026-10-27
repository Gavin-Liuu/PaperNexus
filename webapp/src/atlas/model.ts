import type { Paper, Result } from '../main'

export type Point = { x: number; y: number }
export type MapNode = Point & { id: string; title: string; year: number | null; importance: number; seed: boolean; core: boolean; review: string | null }
export type MapEdge = { source: string; target: string; weight: number; backbone: boolean; reviewLink: boolean }
export type Group = Point & { id: string; members: string[]; label: string; importance: number; reason: string }
export type AtlasModel = { nodes: MapNode[]; edges: MapEdge[]; groups: Group[]; core: string[]; reviewMode: boolean }
export function intersectsViewport(x: number, y: number, width: number, height: number, viewport: { width: number; height: number }): boolean {
  return x + width / 2 > 0 && x - width / 2 < viewport.width && y + height / 2 > 0 && y - height / 2 < viewport.height
}
const clamp = (n: number) => Math.max(0, Math.min(1, n))
const pair = (a: string, b: string) => `${a}\0${b}`

export type ViewMode = 'auto' | 'research' | 'review'
const stopwords = new Set('a an the of for to in on and with by from using based via new towards through research study studies method methods approach model models review survey overview'.split(' '))
const terms = (title: string) => new Set((title.toLowerCase().match(/[\p{L}][\p{L}\p{N}-]*/gu) ?? []).filter(w => w.length > 2 && !stopwords.has(w)))
export function reviewStatus(paper: Paper): string | null {
  if (paper.document_type?.toLowerCase() === 'review') return 'Review'
  return /\b(review|survey|overview)\b|\u7EFC\u8FF0|\u7D9C\u8FF0/i.test(paper.title) ? 'Possible review' : null
}
export function affinity(a: Paper, b: Paper): number {
  const left = terms(a.title), right = terms(b.title)
  const shared = [...left].filter(w => right.has(w)).length
  // A common citation, a publication year or a single generic keyword is not
  // enough to assert topic coherence. No field-specific vocabulary is used.
  if (shared < 2) return 0
  return shared / Math.max(1, Math.min(left.size, right.size))
}
export function summarize(titles: string[]): string {
  const docs = titles.map(terms), counts = new Map<string, number>()
  docs.forEach(words => words.forEach(w => counts.set(w, (counts.get(w) ?? 0) + 1)))
  const shared = [...counts].filter(([, count]) => count >= Math.max(2, Math.ceil(titles.length * .6)))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8).map(([word]) => word)
  // Do not pad to five words with claims that apply to only one member.
  return shared.length >= 2 ? shared.join(' · ') : 'Unresolved citation cluster'
}

export function buildAtlas(graph: Result, mode: ViewMode = 'auto'): AtlasModel {
  const papers = Object.values(graph.papers).sort((a, b) => (a.year ?? 9999) - (b.year ?? 9999) || a.id.localeCompare(b.id))
  const ids = new Set(papers.map(p => p.id))
  const seeds = new Set(graph.seeds.filter(id => ids.has(id)))
  const reviews = new Map(papers.map(p => [p.id, seeds.has(p.id) && mode !== 'auto' ? (mode === 'review' ? 'Review view' : null) : reviewStatus(p)]))
  const reviewMode = [...seeds].some(id => reviews.get(id))
  const importance = new Map(papers.map(p => {
    const c = graph.candidates[p.id]
    return [p.id, clamp(c ? .62 * (c.relevance_score ?? 0) + .23 * (c.route_score ?? 0) + .1 * (c.bridge_score ?? 0) + .05 * (c.influence_score ?? 0) : .3)]
  }))
  let edges: MapEdge[] = []
  const seen = new Set<string>()
  for (const e of graph.edges) {
    if (e.type !== 'citation' || !ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue
    const a = graph.papers[e.source], b = graph.papers[e.target]
    // Unknown dates cannot silently determine a chronological route.
    if (a.year == null || b.year == null || a.year > b.year) continue
    if (seen.has(pair(e.source, e.target))) continue
    seen.add(pair(e.source, e.target))
    const relevance = Math.sqrt((importance.get(e.source) ?? 0) * (importance.get(e.target) ?? 0))
    const weight = clamp(.65 * relevance + .35 * (e.evidence_weight ?? e.display_weight ?? relevance))
    edges.push({ source: e.source, target: e.target, weight, backbone: false, reviewLink: Boolean(reviews.get(e.source) || reviews.get(e.target)) })
  }

  // Same-year citation order comes from evidence, never lexical paper IDs.
  // Exclude every edge in a genuine citation cycle rather than inventing an
  // order by arbitrarily removing one of its edges. Raw evidence stays intact.
  const adjacency = new Map(papers.map(p => [p.id, [] as string[]]))
  edges.forEach(e => adjacency.get(e.source)!.push(e.target))
  const reaches = (start: string, end: string) => {
    const pending = [start], visited = new Set<string>()
    while (pending.length) {
      const id = pending.pop()!
      if (id === end) return true
      if (visited.has(id)) continue
      visited.add(id); pending.push(...adjacency.get(id)!)
    }
    return false
  }
  edges = edges.filter(e => graph.papers[e.source].year !== graph.papers[e.target].year || !reaches(e.target, e.source))
  const indegree = new Map(papers.map(p => [p.id, 0]))
  edges.forEach(e => indegree.set(e.target, indegree.get(e.target)! + 1))
  const pending = [...papers], orderedPapers: Paper[] = []
  while (pending.length) {
    const index = pending.findIndex(p => indegree.get(p.id) === 0)
    const [paper] = pending.splice(index, 1)
    orderedPapers.push(paper)
    edges.filter(e => e.source === paper.id).forEach(e => indegree.set(e.target, indegree.get(e.target)! - 1))
  }
  papers.splice(0, papers.length, ...orderedPapers)
  const rank = new Map(papers.map((p, i) => [p.id, i]))

  // Keep independent, comparably weighted citation branches at every merge.
  // A review is a literature entry point, never a newly invented breakthrough.
  const causal = edges.filter(e => !e.reviewLink)
  const reachMemo = new Map<string, Set<string>>()
  const descendants = (id: string): Set<string> => {
    if (reachMemo.has(id)) return reachMemo.get(id)!
    const found = new Set<string>()
    for (const e of causal.filter(e => e.source === id)) {
      found.add(e.target); descendants(e.target).forEach(n => found.add(n))
    }
    reachMemo.set(id, found); return found
  }
  const coreSet = new Set(seeds)
  const independent = (links: MapEdge[], backward: boolean) => {
    const strongest = Math.max(0, ...links.map(e => e.weight))
    const eligible = links.filter(e => e.weight >= strongest * .78)
    return eligible.filter(e => !eligible.some(other => other !== e && (backward
      ? descendants(e.source).has(other.source)
      : descendants(other.target).has(e.target))))
  }
  type Path = { ids: string[]; score: number }
  const paths = (reverse: boolean) => {
    const table = new Map<string, Path[]>()
    for (const p of reverse ? [...papers].reverse() : papers) {
      const best: Path[] = [{ ids: [p.id], score: importance.get(p.id) ?? 0 }]
      for (const e of causal.filter(e => (reverse ? e.source : e.target) === p.id)) {
        for (const prev of table.get(reverse ? e.target : e.source) ?? []) {
          if (prev.ids.length >= 8) continue
          const next = { ids: [...prev.ids, p.id], score: prev.score + .15 + e.weight ** 1.7 }
          const length = next.ids.length - 1
          if (!best[length] || next.score > best[length].score) best[length] = next
        }
      }
      table.set(p.id, best.filter(Boolean))
    }
    return table
  }
  const before = paths(false), after = paths(true)
  const include = (chain: string[]) => {
    chain.forEach(id => coreSet.add(id))
    for (let i = 1; i < chain.length; i++) {
      const e = causal.find(e => e.source === chain[i - 1] && e.target === chain[i])
      if (e) e.backbone = true
    }
  }
  // Readability budget, not a fixed number or depth of thematic branches.
  // Every omitted paper remains in the expandable exploration graph.
  const coreBudget = 18
  for (const seed of seeds) {
    if (reviews.get(seed)) {
      const coverage = independent(edges.filter(e => e.target === seed && !reviews.get(e.source)), true)
      for (const e of coverage.sort((a, b) => b.weight - a.weight)) {
        const candidates = (before.get(e.source) ?? []).filter(p => new Set([...coreSet, ...p.ids]).size <= coreBudget)
        const path = candidates.sort((a, b) => b.score - a.score)[0]
        if (path) include(path.ids)
      }
    } else {
      const choices: Path[] = []
      for (const left of before.get(seed) ?? []) for (const right of after.get(seed) ?? []) {
        const ids = [...left.ids, ...right.ids.slice(0, -1).reverse()]
        if (ids.length <= 8) choices.push({ ids, score: left.score + right.score })
      }
      const best = choices.sort((a, b) => b.score - a.score)[0]
      if (best) include(best.ids)
    }
  }
  // Add independent tributaries to existing junctions. Do not discard a
  // diamond's second incoming edge as an undirected spanning tree would.
  for (const join of coreSet) {
    if (reviews.get(join)) continue
    const links = independent(causal.filter(e => e.target === join), true).sort((a, b) => b.weight - a.weight)
    for (const e of links) {
      const candidates = (before.get(e.source) ?? []).filter(p => new Set([...coreSet, ...p.ids]).size <= coreBudget)
      const path = candidates.sort((a, b) => b.score - a.score)[0]
      if (path) include([...path.ids, join])
    }
  }
  const core = papers.filter(p => coreSet.has(p.id)).map(p => p.id)

  // Weighted maximum-spanning merges group connected side papers. No fixed
  // branch depth/count, no assignment based on array index or route number.
  const parent = new Map(papers.filter(p => !coreSet.has(p.id)).map(p => [p.id, p.id]))
  const membersByRoot = new Map([...parent.keys()].map(id => [id, [id]]))
  const sizes = new Map([...parent.keys()].map(id => [id, 1]))
  const root = (id: string): string => parent.get(id) === id ? id : root(parent.get(id)!)
  for (const e of [...edges].sort((a, b) => b.weight - a.weight || a.source.localeCompare(b.source))) {
    if (!parent.has(e.source) || !parent.has(e.target)) continue
    const a = root(e.source), b = root(e.target)
    if (a === b || sizes.get(a)! + sizes.get(b)! > 12) continue
    const left = membersByRoot.get(a)!, right = membersByRoot.get(b)!
    const combined = [...left, ...right]
    const years = combined.map(id => graph.papers[id].year).filter((y): y is number => y != null)
    if (combined.some(id => reviews.get(id)) || (years.length && Math.max(...years) - Math.min(...years) > 15)) continue
    // Complete-link coherence prevents a chain of pairwise matches from
    // merging unrelated endpoints into a misleading topic summary.
    if (!left.every(l => right.every(r => affinity(graph.papers[l], graph.papers[r]) >= .28))) continue
    parent.set(b, a); sizes.set(a, combined.length); membersByRoot.set(a, combined)
  }
  const components = new Map<string, string[]>()
  parent.forEach((_, id) => { const r = root(id); components.set(r, [...(components.get(r) ?? []), id]) })
  // Sibling components may merge only with shared bibliographic context AND
  // cross-member topic agreement. A review citing two topics is insufficient.
  const context = (members: string[]) => new Set(edges.filter(e =>
    (members.includes(e.source) && coreSet.has(e.target)) || (members.includes(e.target) && coreSet.has(e.source)))
    .map(e => coreSet.has(e.source) ? e.source : e.target))
  for (const [a, left] of components) for (const [b, right] of components) {
    if (a === b || !components.has(a) || !components.has(b) || left.length + right.length > 12) continue
    const refs = context(left), related = [...context(right)].some(id => refs.has(id))
    const years = [...left, ...right].map(id => graph.papers[id].year).filter((y): y is number => y != null)
    if (!related || [...left, ...right].some(id => reviews.get(id)) || (years.length && Math.max(...years) - Math.min(...years) > 15)) continue
    if (!left.every(l => right.every(r => affinity(graph.papers[l], graph.papers[r]) >= .35))) continue
    left.push(...right); components.delete(b)
  }
  const nodes = new Map<string, MapNode>()
  let nextLane = 0, lastYear: number | null | undefined = undefined, yearY = -148, previousY = -148
  for (const id of core) {
    const paper = graph.papers[id]
    if (paper.year !== lastYear) { yearY = previousY + 148; lastYear = paper.year }
    const parents = edges.filter(e => e.backbone && e.target === id).map(e => nodes.get(e.source)!).filter(Boolean)
    let x = parents.length ? parents.reduce((sum, n) => sum + n.x, 0) / parents.length : (nextLane++ * 420)
    let y = Math.max(previousY, yearY, ...parents.map(n => n.y + 148))
    if (reviews.get(id)) x = Math.max(0, ...[...nodes.values()].map(n => n.x)) + 450
    while ([...nodes.values()].some(n => Math.abs(n.x - x) < 280 && Math.abs(n.y - y) < 100)) x += 340
    nodes.set(id, { id, title: paper.title, year: paper.year, x, y, core: true, seed: seeds.has(id), importance: importance.get(id)!, review: reviews.get(id) ?? null })
    previousY = Math.max(previousY, y)
  }
  const timelineY = (id: string) => {
    const r = rank.get(id)!
    if (!core.length) return r * 100
    const later = core.findIndex(c => rank.get(c)! > r)
    if (later === 0) return nodes.get(core[0])!.y + (r - rank.get(core[0])!) * 50
    if (later < 0) return nodes.get(core[core.length - 1])!.y + (r - rank.get(core[core.length - 1])!) * 50
    const left = rank.get(core[later - 1])!, right = rank.get(core[later])!
    return nodes.get(core[later - 1])!.y + (r - left) / (right - left) * (nodes.get(core[later])!.y - nodes.get(core[later - 1])!.y)
  }
  const groups: Group[] = []
  const occupied: { x: number; y: number }[] = []
  const ordered = [...components.values()].sort((a, b) => Math.max(...b.map(id => importance.get(id)!)) - Math.max(...a.map(id => importance.get(id)!)))
  ordered.forEach(members => {
    const chronological = [...members].sort((a, b) => rank.get(a)! - rank.get(b)!)
    let y = timelineY(chronological[Math.floor(chronological.length / 2)])
    const extent = Math.max(0, ...core.map(id => nodes.get(id)!.x))
    const choices = [-490, extent + 490, -980, extent + 980, -1470, extent + 1470]
    let x = choices[0], cost = Infinity, bestY = y
    for (const cx of choices) {
      for (let offset = 0; offset < 30; offset++) {
        const cy = y + (offset % 2 ? -1 : 1) * Math.ceil(offset / 2) * 170
        if (occupied.some(p => p.x === cx && Math.abs(p.y - cy) < 160)) continue
        const c = Math.abs(cx) * .6 + Math.abs(cy - y)
        if (c < cost) { cost = c; x = cx; bestY = cy }
        break
      }
    }
    y = bestY; occupied.push({ x, y })
    // Leaf coordinates are fixed across every zoom transition.
    chronological.forEach((id, i) => {
      const py = timelineY(id)
      let px = x + (i % 2 ? 145 : -145)
      while ([...nodes.values()].some(n => Math.abs(n.x - px) < 270 && Math.abs(n.y - py) < 100)) px += Math.sign(x) * 280
      nodes.set(id, { id, title: graph.papers[id].title, year: graph.papers[id].year, x: px, y: py, core: false, seed: false, importance: importance.get(id)!, review: reviews.get(id) ?? null })
    })
    groups.push({ id: `group:${members[0]}`, members, label: summarize(members.map(id => graph.papers[id].title)), reason: 'Shared title terms and citation context; not a single paper or confirmed intellectual inheritance', x, y, importance: Math.max(...members.map(id => importance.get(id)!)) })
  })
  return { nodes: [...nodes.values()], edges, groups, core, reviewMode }
}

export function zoomAt(camera: Point & { scale: number }, focus: Point, scale: number) {
  return { x: focus.x - (focus.x - camera.x) * scale / camera.scale, y: focus.y - (focus.y - camera.y) * scale / camera.scale, scale }
}

export function shouldExpand(scale: number, expanded: boolean): boolean {
  // Hysteresis avoids flicker near the semantic zoom boundary.
  return expanded ? scale > .94 : scale > 1.14
}

// Normalize mouse-wheel and trackpad delta modes; cap one event to ~10%.
export function wheelScale(scale: number, deltaY: number, deltaMode = 0): number {
  const pixels = deltaY * (deltaMode === 1 ? 16 : deltaMode === 2 ? 800 : 1)
  return Math.max(.12, Math.min(3.5, scale * Math.exp(-Math.max(-100, Math.min(100, pixels)) * .0009)))
}
