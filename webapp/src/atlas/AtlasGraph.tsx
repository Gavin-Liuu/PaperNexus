import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import type { Result } from '../main'
import { buildAtlas, shouldExpand, zoomAt, wheelScale, summarize, intersectsViewport } from './model'
import type { Point, ViewMode } from './model'
import './atlas.css'

type Camera = Point & { scale: number }
type DisplayNode = Point & { id: string; title: string; importance: number; core: boolean; seed: boolean; members: string[]; year: string; group: boolean; review: string | null; reason?: string }
type Rect = Point & { width: number; height: number }
const overlaps = (a: Rect, b: Rect) => Math.abs(a.x - b.x) < (a.width + b.width) / 2 + 10 && Math.abs(a.y - b.y) < (a.height + b.height) / 2 + 8
const CARD_W = 222, CARD_H = 76

function lines(text: string): string[] {
  // A measured two-line footprint matches the card used by collision testing.
  const context = document.createElement('canvas').getContext('2d')!
  context.font = '12px system-ui'
  const words = text.split(/\s+/), result: string[] = []
  let line = ''
  while (words.length && result.length < 2) {
    const word = words.shift()!
    const candidate = line ? `${line} ${word}` : word
    if (context.measureText(candidate).width > CARD_W - 26 && line) {
      result.push(line); line = word
    } else line = candidate
  }
  if (result.length < 2 && line) result.push(line)
  if (words.length || result.length === 2 && line !== result[1]) result[1] = `${result[1] ?? line}…`
  return result.slice(0, 2).map(s => {
    while (context.measureText(s).width > CARD_W - 26) s = s.slice(0, -2) + '…'
    return s
  })
}

export function AtlasGraph({ graph, selected, setSelected }: { graph: Result; selected: string | null; setSelected: (id: string) => void }) {
  const [mode, setMode] = useState<ViewMode>('auto')
  const model = useMemo(() => buildAtlas(graph, mode), [graph, mode])
  const panel = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ width: 900, height: 710 })
  const [camera, setCamera] = useState<Camera>({ x: 450, y: 70, scale: .65 })
  const cameraRef = useRef(camera); cameraRef.current = camera
  const expanded = useRef(new Set<string>())
  const drag = useRef<{ pointer: number; start: Point; camera: Camera; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const [hover, setHover] = useState<string | null>(null)
  const marker = useId().replace(/:/g, '')
  const reset = () => {
    const core = model.nodes.filter(n => n.core)
    const minX = Math.min(0, ...core.map(n => n.x)), maxX = Math.max(0, ...core.map(n => n.x))
    const minY = Math.min(0, ...core.map(n => n.y)), maxY = Math.max(148, ...core.map(n => n.y))
    const scale = Math.max(.12, Math.min(.9, (size.height - 150) / (maxY - minY), (size.width - 260) / Math.max(400, maxX - minX + (model.groups.length ? 980 : 0))))
    expanded.current.clear()
    setCamera({ x: size.width / 2 - (minX + maxX) / 2 * scale, y: size.height / 2 - (minY + maxY) / 2 * scale, scale })
  }
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    if (panel.current) observer.observe(panel.current)
    return () => observer.disconnect()
  }, [])
  // A new dataset resets the view; selecting a paper never does.
  useEffect(() => { reset() }, [model, size.width, size.height])
  useEffect(() => {
    const element = svg.current
    if (!element) return
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      const bounds = element.getBoundingClientRect(), old = cameraRef.current
      const next = zoomAt(old, { x: event.clientX - bounds.left, y: event.clientY - bounds.top }, wheelScale(old.scale, event.deltaY, event.deltaMode))
      cameraRef.current = next; setCamera(next)
    }
    element.addEventListener('wheel', wheel, { passive: false })
    return () => element.removeEventListener('wheel', wheel)
  }, [])

  const representation = useMemo(() => {
    const nodes: DisplayNode[] = [], owner = new Map<string, string>()
    const byId = new Map(model.nodes.map(n => [n.id, n]))
    const addPaper = (id: string) => {
      const n = byId.get(id)!
      nodes.push({ ...n, members: [id], group: false, year: n.year?.toString() ?? 'Year unknown' }); owner.set(id, id)
    }
    model.core.forEach(addPaper)
    for (const group of model.groups) {
      const sx = group.x * camera.scale + camera.x, sy = group.y * camera.scale + camera.y
      const nearView = sx > -400 && sx < size.width + 400 && sy > -400 && sy < size.height + 400
      const open = nearView && shouldExpand(camera.scale, expanded.current.has(group.id))
      if (open) expanded.current.add(group.id); else expanded.current.delete(group.id)
      const members = group.members.filter(id => id !== selected)
      if (selected && group.members.includes(selected)) addPaper(selected)
      if (open || members.length <= 1) members.forEach(addPaper)
      else {
        const years = members.map(id => byId.get(id)!.year).filter((y): y is number => y !== null)
        nodes.push({ ...group, title: summarize(members.map(id => byId.get(id)!.title)), core: false, seed: false, members, group: true, review: null, year: years.length ? `${Math.min(...years)}–${Math.max(...years)}` : 'Year unknown' })
        members.forEach(id => owner.set(id, group.id))
      }
    }
    const edges = new Map<string, { source: string; target: string; weight: number; backbone: boolean; reviewLink: boolean; count: number }>()
    for (const e of model.edges) {
      const source = owner.get(e.source), target = owner.get(e.target)
      if (!source || !target || source === target) continue
      const key = `${source}\0${target}`, prev = edges.get(key)
      edges.set(key, { source, target, weight: Math.max(e.weight, prev?.weight ?? 0), backbone: e.backbone || Boolean(prev?.backbone), reviewLink: e.reviewLink || Boolean(prev?.reviewLink), count: (prev?.count ?? 0) + 1 })
    }
    // Maximum-spanning forest retains connectivity with few lines. Additional
    // citations appear only in the focused neighborhood, never as fake links.
    const parents = new Map(nodes.map(n => [n.id, n.id]))
    const root = (id: string): string => parents.get(id) === id ? id : root(parents.get(id)!)
    const focus = hover ?? selected
    const sorted = [...edges.values()].sort((a, b) => Number(b.backbone) - Number(a.backbone) || b.weight - a.weight)
    const focusedEdges = new Set(sorted.filter(e => e.source === focus || e.target === focus).slice(0, 5))
    const visibleEdges = sorted.filter(e => {
      const a = root(e.source), b = root(e.target), connective = a !== b
      if (connective) parents.set(a, b)
      return connective || e.backbone || (camera.scale > .9 && focusedEdges.has(e))
    })
    return { nodes, edges: visibleEdges }
  }, [model, camera, selected, hover, size])

  const display = useMemo(() => {
    const placed: Rect[] = []
    const nodes = [...representation.nodes].sort((a, b) => Number(b.core) - Number(a.core) || Number(b.id === selected) - Number(a.id === selected) || b.importance - a.importance)
    return nodes.map(n => {
      const x = n.x * camera.scale + camera.x, y = n.y * camera.scale + camera.y
      const rect = { x, y, width: CARD_W, height: CARD_H }
      const label = !placed.some(p => overlaps(p, rect))
      const visible = intersectsViewport(x, y, CARD_W, CARD_H, size)
      if (label && visible) placed.push(rect)
      return { ...n, x, y, label, visible, lines: label && visible ? lines(n.title) : [] }
    })
  }, [representation, camera, selected, size])
  const positions = new Map(display.map(n => [n.id, n]))
  const focus = hover ?? selected
  const zoom = (factor: number) => setCamera(old => zoomAt(old, { x: size.width / 2, y: size.height / 2 }, Math.max(.12, Math.min(3.5, old.scale * factor))))

  return <div className="evolution-atlas">
    <div className="evolution-toolbar"><strong>{model.reviewMode ? 'Review topic map' : 'Research evolution'}</strong><span>{model.reviewMode ? 'Dashed: review coverage · Solid: paper citations' : 'Earlier ↓ Later · Multiple paths converge'}</span><select aria-label="Paper view" value={mode} onChange={event => setMode(event.target.value as ViewMode)}><option value="auto">Auto detect</option><option value="research">Research papers</option><option value="review">Review</option></select><div className="evolution-zoom">
      <button aria-label="Zoom out" onClick={() => zoom(1 / 1.15)}><Minus size={16} /></button>
      <button aria-label="Reset view" onClick={reset}><RotateCcw size={15} /></button>
      <button aria-label="Zoom in" onClick={() => zoom(1.15)}><Plus size={16} /></button>
    </div></div>
    <div ref={panel} className="evolution-canvas">
      <svg ref={svg} width={size.width} height={size.height} data-camera={`${camera.x},${camera.y},${camera.scale}`} role="img" aria-label="Zoomable research evolution map"
        onPointerDown={event => { if (event.button !== 0) return; suppressClick.current = false; drag.current = { pointer: event.pointerId, start: { x: event.clientX, y: event.clientY }, camera, moved: false } }}
        onPointerMove={event => {
          const d = drag.current; if (!d || d.pointer !== event.pointerId) return
          const dx = event.clientX - d.start.x, dy = event.clientY - d.start.y
          if (Math.hypot(dx, dy) > 4) { d.moved = true; svg.current?.setPointerCapture(event.pointerId) }
          if (d.moved) setCamera({ ...d.camera, x: d.camera.x + dx, y: d.camera.y + dy })
        }}
        onPointerUp={() => { suppressClick.current = drag.current?.moved ?? false; drag.current = null }}
        onPointerCancel={() => { drag.current = null }}>
        <defs><marker id={marker} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8Z" fill="context-stroke" /></marker></defs>
        {representation.edges.map(e => {
          const a = positions.get(e.source)!, b = positions.get(e.target)!
          // Keep paths whose curve enters the viewport even when one endpoint
          // is outside it. This prevents clipped cards from losing their edge.
          const pathMinX = Math.min(a.x, b.x) - CARD_W / 2
          const pathMaxX = Math.max(a.x, b.x) + CARD_W / 2
          const pathMinY = Math.min(a.y, b.y) - CARD_H / 2
          const pathMaxY = Math.max(a.y, b.y) + CARD_H / 2
          if (pathMaxX <= 0 || pathMinX >= size.width || pathMaxY <= 0 || pathMinY >= size.height) return null
          const down = b.y >= a.y ? 1 : -1
          const ay = a.y + down * (a.label ? CARD_H / 2 : 9), by = b.y - down * (b.label ? CARD_H / 2 : 9)
          const emphasis = e.weight ** 2.2
          const active = camera.scale > .9 && (e.source === focus || e.target === focus)
          return <path key={`${e.source}-${e.target}`} data-backbone={e.backbone} data-review-link={e.reviewLink} className="evolution-edge"
            d={`M${a.x},${ay} C${a.x},${(ay + by) / 2} ${b.x},${(ay + by) / 2} ${b.x},${by}`}
            strokeDasharray={e.reviewLink ? '5 5' : undefined} stroke={e.reviewLink ? '#b5a3d5' : e.backbone ? '#8de4d0' : '#87a8bd'} strokeWidth={.6 + emphasis * 4.4}
            opacity={active ? .8 : e.backbone ? .65 + .35 * emphasis : .08 + .32 * emphasis}
            markerEnd={`url(#${marker})`}><title>{e.count} citation records; {e.reviewLink ? 'The review covers this literature and does not claim these contributions' : 'Arrow points from the cited paper to the citing paper'}</title></path>
        })}
        {display.filter(n => n.visible).map(n => {
          const active = n.id === selected, emphasis = n.importance ** 1.7
          const color = n.review ? '#c6afe9' : n.seed ? '#efbd77' : n.core ? '#8de4d0' : '#9cb7ca'
          return <g key={n.id} transform={`translate(${n.x},${n.y})`} className={`evolution-node ${n.group ? 'aggregate' : ''} ${active ? 'is-selected' : ''}`} data-node-id={n.id} data-group={n.group} data-review={n.review ?? undefined} data-label={n.label}
            role={n.group ? undefined : 'button'} tabIndex={n.group ? undefined : 0}
            aria-label={n.group ? `${n.title}, ${n.members.length} papers, zoom to expand` : n.title}
            onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}
            onClick={() => { if (!suppressClick.current && !n.group) setSelected(n.id) }}
            onKeyDown={event => { if (!n.group && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); setSelected(n.id) } }}>
            <title>{n.group ? `${n.title} · ${n.members.length} papers · ${n.reason}\n${n.members.map(id => graph.papers[id].title).join("\n")}\nZoom in to expand` : n.title}</title>
            {n.label ? <>
              {n.group && <rect x={-CARD_W / 2 + 5} y={-CARD_H / 2 + 5} width={CARD_W} height={CARD_H} rx="10" fill="#132530" stroke="#294350" />}
              <rect x={-CARD_W / 2} y={-CARD_H / 2} width={CARD_W} height={CARD_H} rx="10" fill={n.seed ? '#29261f' : n.core ? '#142a2a' : '#121f29'} stroke={active ? '#ffda9e' : color} strokeOpacity={active ? 1 : .2 + emphasis * .7} strokeWidth={active ? 2 : .6 + emphasis * 1.7} />
              <circle cx={-CARD_W / 2 + 15} cy={-CARD_H / 2 + 15} r={2.5 + 4 * emphasis} fill={color} />
              <text x={-CARD_W / 2 + 29} y={-CARD_H / 2 + 19} className="evolution-meta" fill={color}>{n.year}{n.review ? ` · ${n.review}` : n.seed ? ' · Seed' : n.group ? ` · ${n.members.length} papers · Zoom to expand` : ''}</text>
              {n.lines.map((line, i) => <text key={i} x={-CARD_W / 2 + 13} y={0 + i * 17} className="evolution-title">{line}</text>)}
            </> : <circle r={4 + emphasis * 9} fill={color} opacity={.35 + .65 * emphasis} stroke={active ? '#fff' : '#152733'} strokeWidth="2" />}
          </g>
        })}
        {!model.nodes.length && <text x="50%" y="50%" textAnchor="middle" fill="#a4b7c1">No papers to display</text>}
      </svg>
      <div className="evolution-hint">Scroll to zoom · Drag to pan · Zoom out to merge side branches</div>
    </div>
    <div className="evolution-footer"><span>{model.edges.some(e => e.backbone) ? 'Verifiable citation route · Not a complete field history' : 'Not enough evidence to connect a main route'}</span><span>{display.filter(n => n.visible && !n.group).length} visible · {display.filter(n => n.visible && n.group).length} aggregates · {model.nodes.length} total</span></div>
  </div>
}
