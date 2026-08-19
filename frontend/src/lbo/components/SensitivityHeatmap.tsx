import { useMemo, useState } from 'react'
import type { SensitivityCell } from '../types'
import styles from './SensitivityHeatmap.module.css'

interface Props {
  cells: SensitivityCell[]
}

type View = 'moic' | 'irr'

function cellColor(view: View, value: number): string {
  if (view === 'moic') {
    if (value >= 2.5) return 'rgba(61, 140, 104, 0.28)'
    if (value >= 1.8) return 'rgba(184, 140, 58, 0.24)'
    return 'rgba(176, 90, 82, 0.24)'
  }
  if (value >= 0.2) return 'rgba(61, 140, 104, 0.28)'
  if (value >= 0.15) return 'rgba(184, 140, 58, 0.24)'
  return 'rgba(176, 90, 82, 0.24)'
}

export function SensitivityHeatmap({ cells }: Props) {
  const [view, setView] = useState<View>('moic')
  const [collapsed, setCollapsed] = useState(false)

  const { entries, exits, grid } = useMemo(() => {
    const entries = [...new Set(cells.map((c) => c.entryMultiple))].sort((a, b) => a - b)
    const exits = [...new Set(cells.map((c) => c.exitMultiple))].sort((a, b) => b - a)
    const map = new Map(cells.map((c) => [`${c.entryMultiple}|${c.exitMultiple}`, c]))
    return { entries, exits, grid: map }
  }, [cells])

  return (
    <section className={`tile tile-sensitivity collapsible ${collapsed ? 'collapsed' : ''}`}>
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setCollapsed((c) => !c)}
      >
        Sensitivity Heatmap
        <span>{collapsed ? '+' : '−'}</span>
      </button>
      <div className={styles.header}>
        <h2 className="tile-title" style={{ marginBottom: 0 }}>
          Sensitivity Heatmap
        </h2>
        <div className={styles.toggle}>
          <button
            type="button"
            className={view === 'moic' ? styles.active : ''}
            onClick={() => setView('moic')}
          >
            MOIC
          </button>
          <button
            type="button"
            className={view === 'irr' ? styles.active : ''}
            onClick={() => setView('irr')}
          >
            IRR
          </button>
        </div>
      </div>
      <div className="collapsible-body">
        <p className={styles.axisHint}>Entry Multiple → · Exit Multiple ↓</p>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th />
                {entries.map((e) => (
                  <th key={e} className="mono">
                    {e.toFixed(1)}x
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {exits.map((ex) => (
                <tr key={ex}>
                  <th className="mono">{ex.toFixed(1)}x</th>
                  {entries.map((en) => {
                    const cell = grid.get(`${en}|${ex}`)
                    if (!cell) return <td key={en} />
                    const val = view === 'moic' ? cell.moic : cell.irr
                    const label =
                      view === 'moic' ? `${cell.moic.toFixed(2)}x` : `${(cell.irr * 100).toFixed(1)}%`
                    return (
                      <td
                        key={en}
                        className={`mono ${cell.isBase ? styles.base : ''}`}
                        style={{ background: cellColor(view, val) }}
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
        <div className={styles.legend}>
          <span>
            <i style={{ background: 'rgba(61, 140, 104, 0.35)' }} /> Strong
          </span>
          <span>
            <i style={{ background: 'rgba(184, 140, 58, 0.3)' }} /> Moderate
          </span>
          <span>
            <i style={{ background: 'rgba(176, 90, 82, 0.3)' }} /> Weak
          </span>
          <span className={styles.baseLegend}>Base case</span>
        </div>
      </div>
    </section>
  )
}
