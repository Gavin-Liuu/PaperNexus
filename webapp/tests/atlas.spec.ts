import { test, expect } from '@playwright/test'
import { buildAtlas, shouldExpand, zoomAt, wheelScale, summarize, reviewStatus, intersectsViewport } from '../src/atlas/model'
import type { Result } from '../src/main'
import { readFileSync } from 'node:fs'

function fixture(): Result {
  const g: Result = { seeds: ['P4'], papers: {}, candidates: {}, edges: [], routes: [], reading_list: [] }
  for (let i = 0; i < 8; i++) {
    const id = `P${i}`
    g.papers[id] = { id, year: 2000 + i * 3, title: `Research milestone ${i}: computational imaging and wave reconstruction` }
    g.candidates[id] = { roles: [], selection_reasons: [], relevance_score: .96, route_score: .9 }
    if (i) g.edges.push({ source: `P${i - 1}`, target: id, type: 'citation', evidence_weight: .95 })
    for (let j = 0; j < 5; j++) {
      const bid = `B${i}-${j}`
      g.papers[bid] = { id: bid, year: 2001 + i * 3 + j, title: `Adaptive wavefront imaging through complex scattering media experiment ${i} ${j}` }
      g.candidates[bid] = { roles: [], selection_reasons: [], relevance_score: .4, route_score: .3 }
      g.edges.push({ source: j ? `B${i}-${j - 1}` : id, target: bid, type: 'citation', evidence_weight: .35 })
    }
  }
  return g
}

test('backbone preserves citation evidence, identity and chronology; zoom preserves focus', () => {
  const g = fixture(), m = buildAtlas(g)
  expect(new Set(m.nodes.map(n => n.id)).size).toBe(Object.keys(g.papers).length)
  expect(m.core).toContain('P4')
  for (const e of m.edges) expect(m.nodes.find(n => n.id === e.source)!.y).toBeLessThanOrEqual(m.nodes.find(n => n.id === e.target)!.y)
  for (const e of m.edges.filter(e => e.backbone)) {
    expect(g.edges.some(raw => raw.source === e.source && raw.target === e.target && raw.type === 'citation')).toBeTruthy()
    expect(g.papers[e.source].year!).toBeLessThanOrEqual(g.papers[e.target].year!)
  }
  expect(m.groups.flatMap(g => g.members).sort()).toEqual(m.nodes.filter(n => !n.core).map(n => n.id).sort())
  const camera = { x: 60, y: 80, scale: .5 }, focus = { x: 340, y: 300 }, next = zoomAt(camera, focus, 1.3)
  expect((focus.x - next.x) / next.scale).toBeCloseTo((focus.x - camera.x) / camera.scale)
  expect((focus.y - next.y) / next.scale).toBeCloseTo((focus.y - camera.y) / camera.scale)
  expect(shouldExpand(1.02, true)).toBe(true)
  expect(shouldExpand(1.02, false)).toBe(false)
})

test('overview is readable, zoom expands locally, selection preserves camera, reset collapses', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const graph: Result = process.env.ATLAS_FIXTURE ? JSON.parse(readFileSync(process.env.ATLAS_FIXTURE, 'utf8')) : fixture()
  await page.route('**/api/v1/**', route => {
    const url = route.request().url()
    const body = url.endsWith('/searches') ? [{ graph_id: 'sample', seed_titles: ['Sample'], seeds: ['seed'], paper_count: Object.keys(graph.papers).length, created_at: '2026-09-18' }] : graph
    return route.fulfill({ json: body })
  })
  await page.goto('/')
  await page.locator('#saved-searches').selectOption('sample')
  const canvas = page.locator('.evolution-canvas')
  await expect(canvas).toBeVisible()
  await expect(page.locator('[data-backbone="true"]')).not.toHaveCount(0)
  const cards = await page.locator('.evolution-node[data-label="true"]').evaluateAll(nodes => nodes.map(n => n.getBoundingClientRect().toJSON()))
  for (let i = 0; i < cards.length; i++) for (let j = 0; j < i; j++) {
    const a = cards[i], b = cards[j]
    expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top).toBeTruthy()
  }
  if (process.env.ATLAS_SCREENSHOTS) await page.screenshot({ path: 'test-results/atlas-overview.png', fullPage: true })
  const group = page.locator('.evolution-node[data-group="true"][data-label="true"]').first()
  const groupId = await group.getAttribute('data-node-id')
  await group.scrollIntoViewIfNeeded()
  const bounds = await group.boundingBox()
  const initialCamera = await canvas.locator('svg').getAttribute('data-camera')
  expect(bounds).not.toBeNull()
  await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2)
  for (let i = 0; i < 40; i++) {
    if (Number((await canvas.locator('svg').getAttribute('data-camera'))!.split(',')[2]) > 1.2) break
    await page.mouse.wheel(0, -120); await page.waitForTimeout(40)
  }
  await expect(page.locator(`[data-node-id="${groupId}"]`)).toHaveCount(0)
  const zoomedCamera = await canvas.locator('svg').getAttribute('data-camera')
  expect(zoomedCamera).not.toEqual(initialCamera)
  // SVG nodes may have a box outside the clipped canvas. Choose a paper
  // that is actually under the pointer, not merely present in the SVG tree.
  const paperId = await page.locator('.evolution-node[data-group="false"][data-label="true"]').evaluateAll(nodes => {
    const node = nodes.find(n => {
      const box = n.getBoundingClientRect()
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return hit && n.contains(hit)
    })
    return node?.getAttribute('data-node-id')
  })
  expect(paperId).toBeTruthy()
  const paper = page.locator(`[data-node-id="${paperId}"]`)
  const before = await paper.getAttribute('transform')
  await paper.click()
  await expect(canvas.locator('svg')).toHaveAttribute('data-camera', zoomedCamera!)
  await expect(paper).toHaveAttribute('transform', before!)
  if (process.env.ATLAS_SCREENSHOTS) await page.screenshot({ path: 'test-results/atlas-detail.png', fullPage: true })
  await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2)
  for (let i = 0; i < 25; i++) {
    if (Number((await canvas.locator('svg').getAttribute('data-camera'))!.split(',')[2]) < .9) break
    await page.mouse.wheel(0, 120); await page.waitForTimeout(40)
  }
  await expect(page.locator('.evolution-node[data-group="true"]')).not.toHaveCount(0)
  await page.getByRole('button', { name: 'Reset view' }).click()
  await expect(page.locator('.evolution-node[data-group="true"]')).not.toHaveCount(0)
  expect(errors).toEqual([])
})

test('independent citation paths converge at one shared paper without losing a diamond edge', () => {
  const g = fixture()
  g.seeds = ['S']; g.papers = {}; g.edges = []; g.candidates = {}
  for (const [id, year] of [['R', 2000], ['A', 2010], ['B', 2010], ['S', 2020]] as const) {
    g.papers[id] = { id, year, title: id }
    g.candidates[id] = { roles: [], selection_reasons: [], relevance_score: .9, route_score: .9 }
  }
  for (const [source, target] of [['R', 'A'], ['R', 'B'], ['A', 'S'], ['B', 'S']]) g.edges.push({ source, target, type: 'citation', evidence_weight: .95 })
  const m = buildAtlas(g)
  expect(m.edges.filter(e => e.backbone)).toHaveLength(4)
  expect(m.nodes.filter(n => n.id === 'S')).toHaveLength(1)
  expect(m.nodes.find(n => n.id === 'A')!.x).not.toEqual(m.nodes.find(n => n.id === 'B')!.x)
})

test('review references stay coverage links; unrelated cited topics are not merged', () => {
  const g: Result = { seeds: ['S'], papers: {
    S: { id: 'S', title: 'A survey of imaging and genome editing', year: 2024, document_type: 'review' },
    A: { id: 'A', title: 'Adaptive optical imaging wavefront reconstruction', year: 2018 },
    B: { id: 'B', title: 'CRISPR gene editing bacterial immunity', year: 2019 },
  }, candidates: {}, edges: [{ source: 'A', target: 'S', type: 'citation' }, { source: 'B', target: 'S', type: 'citation' }], routes: [], reading_list: [] }
  const m = buildAtlas(g)
  expect(m.reviewMode).toBe(true)
  expect(m.edges.every(e => e.reviewLink && !e.backbone)).toBe(true)
  expect(m.groups.some(group => group.members.includes('A') && group.members.includes('B'))).toBe(false)
  expect(buildAtlas(g, 'research').reviewMode).toBe(false)
  expect(reviewStatus({ id: 'X', title: 'Neural imaging with 300 references', year: 2020 })).toBeNull()
})

test('aggregate labels use shared terms and cannot drift across topics along a citation chain', () => {
  const g: Result = { seeds: ['S'], papers: {
    S: { id: 'S', title: 'Seed', year: 2024 },
    A: { id: 'A', title: 'Adaptive optical imaging reconstruction', year: 2018 },
    B: { id: 'B', title: 'Robust optical imaging reconstruction', year: 2019 },
    C: { id: 'C', title: 'CRISPR gene editing immunity', year: 2020 },
  }, candidates: {}, edges: [{ source: 'A', target: 'B', type: 'citation' }, { source: 'B', target: 'C', type: 'citation' }], routes: [], reading_list: [] }
  const m = buildAtlas(g), group = m.groups.find(g => g.members.includes('A'))!
  expect(group.members.sort()).toEqual(['A', 'B'])
  expect(group.label).not.toMatch(/adaptive|robust/i)
  expect(summarize(['Optical imaging lenses', 'CRISPR genome editing'])).toContain('Unresolved')
})

test('wheel steps are gentle, normalized and reversible without moving the focal paper', () => {
  expect(wheelScale(1, -120)).toBeLessThan(1.1)
  expect(wheelScale(1, -120)).toBeGreaterThan(1)
  expect(wheelScale(wheelScale(1, -120), 120)).toBeCloseTo(1)
  expect(wheelScale(1, 3, 1)).toBeCloseTo(wheelScale(1, 48, 0))
  expect(wheelScale(1, -10000, 2)).toBeLessThan(1.1)
})

test('same-year citation ordering follows evidence and excludes genuine cycles', () => {
  const g: Result = { seeds: ['A'], papers: {
    A: { id: 'A', title: 'Later paper', year: 2020 },
    Z: { id: 'Z', title: 'Earlier paper', year: 2020 },
  }, candidates: {}, edges: [{ source: 'Z', target: 'A', type: 'citation' }], routes: [], reading_list: [] }
  const m = buildAtlas(g)
  expect(m.edges).toHaveLength(1)
  expect(m.edges[0].backbone).toBe(true)
  expect(m.nodes.find(n => n.id === 'Z')!.y).toBeLessThan(m.nodes.find(n => n.id === 'A')!.y)
  g.edges.push({ source: 'A', target: 'Z', type: 'citation' })
  expect(buildAtlas(g).edges).toHaveLength(0)
  expect(g.edges).toHaveLength(2)
})

test('review view renders coverage links distinctly and permits manual correction', async ({ page }) => {
  const graph: Result = { seeds: ['S'], papers: {
    S: { id: 'S', title: 'Imaging overview', year: 2024, document_type: 'review' },
    A: { id: 'A', title: 'Adaptive optical reconstruction', year: 2010 },
    B: { id: 'B', title: 'Genome editing techniques', year: 2011 },
  }, candidates: {}, edges: [{ source: 'A', target: 'S', type: 'citation' }, { source: 'B', target: 'S', type: 'citation' }], routes: [], reading_list: [] }
  await page.route('**/api/v1/**', route => route.fulfill({ json: route.request().url().endsWith('/searches')
    ? [{ graph_id: 'review', seed_titles: ['Overview'], seeds: ['S'], paper_count: 3, created_at: '2026-09-18' }] : graph }))
  await page.goto('/')
  await page.locator('#saved-searches').selectOption('review')
  await expect(page.locator('.evolution-toolbar strong')).toHaveText('Review topic map')
  await expect(page.locator('[data-review-link="true"]')).toHaveCount(2)
  await expect(page.locator('[data-backbone="true"]')).toHaveCount(0)
  await expect(page.locator('[data-review-link="true"]').first()).toHaveAttribute('stroke-dasharray', '5 5')
  await page.getByLabel('Paper view').selectOption('research')
  await expect(page.locator('.evolution-toolbar strong')).toHaveText('Research evolution')
  await expect(page.locator('[data-review-link="true"]')).toHaveCount(0)
  await expect(page.locator('[data-backbone="true"]')).toHaveCount(2)
})

test('partially clipped cards still count as visible geometry', () => {
  expect(intersectsViewport(-100, 80, 222, 76, { width: 900, height: 700 })).toBe(true)
  expect(intersectsViewport(-200, 80, 222, 76, { width: 900, height: 700 })).toBe(false)
  expect(intersectsViewport(450, -20, 222, 76, { width: 900, height: 700 })).toBe(true)
})
