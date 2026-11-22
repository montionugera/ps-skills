import { useEffect, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'

const SECTIONS = [
  { id: 's1', label: '1. Interactive Simulator' },
]

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

const STAGES = [
  { key: 'init', label: '1. init.sh', detail: 'Creates /tmp workspace and copies shared Cream theme + vendored assets.' },
  { key: 'lint', label: '2. lint.sh', detail: 'Verifies 00-brief.md, 01-facts.md, 02-storyboard.md, and Lang: tags.' },
  { key: 'serve', label: '3. serve.sh', detail: 'Binds 127.0.0.1 only and optionally exposes tailnet HTTPS via serve.' },
]

/** SAMPLE interactive component — replace per topic. Demonstrates filter +
 *  step simulator + slider state that justifies the React tier. */
function InteractiveLab() {
  const [n, setN] = useState(4)
  const [stepIdx, setStepIdx] = useState(0)
  const [filter, setFilter] = useState<'all' | 'fast' | 'safe'>('all')

  const rows = [
    { name: 'Loopback bind', tag: 'safe', latency: n },
    { name: 'Static cache bypass', tag: 'fast', latency: n * 2 },
    { name: 'Marker PID verify', tag: 'safe', latency: n + 3 },
  ].filter((r) => filter === 'all' || r.tag === filter)

  return (
    <div className="panel">
      <div className="control-row">
        <label className="slider-label" htmlFor="window-size-range">
          <span>Batch size: <strong>{n}</strong></span>
          <input
            id="window-size-range"
            type="range"
            min={1}
            max={16}
            value={n}
            onChange={(e) => setN(+e.target.value)}
          />
        </label>
        <div className="readout-box">
          <span className="readout-k">Estimated budget</span>
          <strong className="readout-v">{n * 2} ms</strong>
        </div>
      </div>

      <div className="filter-bar" role="group" aria-label="Filter checks">
        {(['all', 'safe', 'fast'] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            className={`pill-btn ${filter === kind ? 'is-active' : ''}`}
            aria-pressed={filter === kind}
            onClick={() => setFilter(kind)}
          >
            Filter: {kind}
          </button>
        ))}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Stage check</th>
              <th>Category</th>
              <th>Budget</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td data-label="Stage check"><div className="td-val">{r.name}</div></td>
                <td data-label="Category"><div className="td-val">{r.tag}</div></td>
                <td data-label="Budget"><div className="td-val">{r.latency} ms</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="stepper">
        <div className="step-controls">
          {STAGES.map((st, idx) => (
            <button
              key={st.key}
              type="button"
              className={`pill-btn ${stepIdx === idx ? 'is-active' : ''}`}
              aria-pressed={stepIdx === idx}
              onClick={() => setStepIdx(idx)}
            >
              {st.label}
            </button>
          ))}
        </div>
        {STAGES.map((st, idx) => (
          <p key={st.key} className="step-detail" hidden={idx !== stepIdx}>
            {st.detail}
          </p>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [activeId, setActiveId] = useState(SECTIONS[0]?.id ?? 's1')
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    document.body.classList.add('has-nav')
    const els = SECTIONS
      .map((s) => ({ id: s.id, el: document.getElementById(s.id) }))
      .filter((x): x is { id: string; el: HTMLElement } => x.el !== null)
    if (!els.length) return () => { document.body.classList.remove('has-nav') }

    const recompute = () => {
      const nearBottom =
        window.scrollY > 0 &&
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 48
      if (nearBottom) {
        setActiveId(els[els.length - 1].id)
        return
      }
      const line = window.innerHeight * 0.45
      let current = els[0].id
      for (const item of els) {
        if (item.el.getBoundingClientRect().top <= line) current = item.id
        else break
      }
      setActiveId(current)
    }

    const io = typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(recompute, { rootMargin: '0px 0px -45% 0px', threshold: [0, 1] })
      : null
    if (io) els.forEach((item) => io.observe(item.el))
    window.addEventListener('scroll', recompute, { passive: true })
    window.addEventListener('resize', recompute, { passive: true })
    recompute()

    return () => {
      document.body.classList.remove('has-nav')
      if (io) io.disconnect()
      window.removeEventListener('scroll', recompute)
      window.removeEventListener('resize', recompute)
    }
  }, [])

  const handleNavClick = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    const target = document.getElementById(id)
    if (!target) return
    e.preventDefault()
    setNavOpen(false)
    target.scrollIntoView({ block: 'start', behavior: 'instant' as ScrollBehavior })
    history.replaceState(null, '', '#' + id)
    setActiveId(id)
  }

  return (
    <>
      <nav aria-label="Document sections">
        <div className="nav-bar">
          <div className="nav-brand">
            <div className="nav-title">TOPIC TITLE</div>
          </div>
          <button
            type="button"
            className="nav-toggle"
            aria-expanded={navOpen}
            aria-controls="nav-links"
            onClick={() => setNavOpen((v) => !v)}
          >
            Sections
          </button>
        </div>
        <div className="nav-kicker">On this page</div>
        <div id="nav-links" className={`nav-links${navOpen ? ' is-open' : ''}`}>
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`nav-link${activeId === s.id ? ' is-active active' : ''}`}
              onClick={(e) => handleNavClick(e, s.id)}
            >
              {s.label}
            </a>
          ))}
        </div>
      </nav>
      <main>
        <h1>TOPIC TITLE</h1>
        <p className="lead">One-paragraph framing of why this interactive model matters.</p>
        <Section id="s1" title="Interactive Simulator">
          <InteractiveLab />
        </Section>
      </main>
    </>
  )
}
