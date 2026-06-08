import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/** Scroll-reveal wrapper — mirrors the HTML tier's .reveal behavior. */
type Cat = 'lifecycle' | 'safety' | 'perf' | 'cleanup' | 'concept' | 'demo'

function Section({ id, title, cat, children }: { id: string; title: string; cat?: Cat; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => e.isIntersecting && e.target.classList.add('shown')),
      { threshold: 0.12 },
    )
    if (ref.current) io.observe(ref.current)
    return () => io.disconnect()
  }, [])
  return (
    <section id={id} ref={ref} className="reveal" data-cat={cat}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

/** SAMPLE interactive component — replace per topic. Shows the state pattern
 *  that justifies the React tier (spec D1). */
function SliderDemo() {
  const [n, setN] = useState(4)
  return (
    <div className="panel">
      <label>
        window size: {n}
        <input type="range" min={1} max={16} value={n} onChange={(e) => setN(+e.target.value)} />
      </label>
      <div className="metric-grid">
        <div className="metric-tile"><strong>{n * 2}ms</strong>derived value</div>
      </div>
    </div>
  )
}

// nav: not auto-rendered in the React tier — add a <nav> per topic if the
// explanation has 3+ sections (styles.css already ships the nav rules).
export default function App() {
  return (
    <main>
      <h1>TOPIC TITLE</h1>
      <Section id="s1" title="Section One" cat="demo">
        <SliderDemo />
      </Section>
    </main>
  )
}
