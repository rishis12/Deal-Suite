import { useMemo, useState } from 'react'
import type { SensitivityCell } from '../types'
import styles from './SensitivityHeatmap.module.css'

interface Props {
  cells: SensitivityCell[]
}

type View = 'moic' | 'irr'

/** Tinted-cell scale: red for weak, amber for middling, layered greens for
    strong — the base case is the ink cell with gold figures. */
function cellClass(view: View, value: number): string {
  const v = view === 'moic' ? value : value
  if (view === 'moic') {
    if (v < 1.5) return 'hm-neg2'
    if (v < 1.8) return 'hm-warn'
    if (v < 2.2) return 'hm-pos1'
    if (v < 2.6) return 'hm-pos2'
    return 'hm-pos3'
  }
  if (v < 0.1) return 'hm-neg2'
  if (v < 0.15) return 'hm-warn'
  if (v < 0.2) return 'hm-pos1'
  if (v < 0.25) return 'hm-pos2'
  return 'hm-pos3'
}

export function SensitivityHeatmap({ cells }: Props) {
  const [view, setView] = useState<View>('irr')

  const { entries, exits, grid } = useMemo(() => {
    const entries = [...new Set(cells.map((c) => c.entryMultiple))].sort((a, b) => a - b)
    const exits = [...new Set(cells.map((c) => c.exitMultiple))].sort((a, b) => a - b)
    const map = new Map(cells.map((c) => [`${c.entryMultiple}|${c.exitMultiple}`, c]))
    return { entries, exits, grid: map }
  }, [cells])

  return (
    <section className="card card-flush">
      <div className="card-head">
        <span className="card-title">Sensitivity — {view === 'irr' ? 'IRR' : 'MOIC'}</span>
        <div className={styles.headRight}>
          <span className="card-note">Entry multiple × exit multiple</span>
          <div className={styles.toggle}>
            <button
              type="button"
              className={view === 'irr' ? styles.active : ''}
              onClick={() => setView('irr')}
            >
              IRR
            </button>
            <button
              type="button"
              className={view === 'moic' ? styles.active : ''}
              onClick={() => setView('moic')}
            >
              MOIC
            </button>
          </div>
        </div>
      </div>
      <div className="card-body">
        <div className={styles.tableWrap}>
          <table className="hm-table">
            <thead>
              <tr>
                <th />
                {entries.map((e) => (
                  <th key={e}>{e.toFixed(1)}×</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {exits.map((ex) => (
                <tr key={ex}>
                  <th>{ex.toFixed(1)}×</th>
                  {entries.map((en) => {
                    const cell = grid.get(`${en}|${ex}`)
                    if (!cell) return <td key={en} />
                    const val = view === 'moic' ? cell.moic : cell.irr
                    const label =
                      view === 'moic' ? `${cell.moic.toFixed(2)}×` : `${(cell.irr * 100).toFixed(1)}%`
                    return (
                      <td
                        key={en}
                        className={cell.isBase ? 'hm-base' : cellClass(view, val)}
                      >
                        {label}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="hm-legend">
          <span>Base case outlined</span>
          <span>
            <i style={{ background: 'var(--negative-bg)' }} /> weak
          </span>
          <span>
            <i style={{ background: 'var(--warning-bg)' }} /> moderate
          </span>
          <span>
            <i style={{ background: 'var(--pos-4)' }} /> strong
          </span>
          <span className={styles.axes}>rows exit multiple · cols entry multiple</span>
        </div>
      </div>
    </section>
  )
}
