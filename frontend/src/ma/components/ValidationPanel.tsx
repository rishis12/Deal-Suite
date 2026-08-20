import type { CompanyVerdict, PairValidation } from '../types'

interface Row {
  severity: 'Blocking' | 'Warning' | 'Pass'
  company: string
  finding: string
  category: string
}

function rowsFor(verdict: CompanyVerdict): Row[] {
  const rows: Row[] = []
  const seen = new Set<string>()
  const push = (severity: Row['severity'], finding: string, category: string) => {
    if (seen.has(finding)) return
    seen.add(finding)
    rows.push({ severity, company: verdict.ticker, finding, category })
  }
  verdict.disqualifyingReasons.forEach((r) => push('Blocking', r, 'Disqualifying'))
  verdict.missingHard.forEach((r) =>
    push(verdict.status === 'fail' ? 'Blocking' : 'Warning', r, 'Missing'),
  )
  verdict.missingSoft.forEach((r) => push('Warning', r, 'Missing (soft)'))
  verdict.defaultsApplied.forEach((r) => push('Warning', r, 'Defaulted'))
  verdict.substituteWarnings.forEach((r) => push('Warning', r, 'Substituted'))
  verdict.warnings.forEach((r) => push('Warning', r, 'Warning'))
  if (rows.length === 0) {
    push('Pass', 'All required data present — read directly from filed XBRL facts.', 'Filed')
  }
  return rows
}

const badgeClass: Record<Row['severity'], string> = {
  Blocking: 'badge badge-blocking',
  Warning: 'badge badge-warning',
  Pass: 'badge badge-pass',
}

/** Data validation log (frame 1g): banner, five-column log, counters. */
export function ValidationPanel({ validation }: { validation: PairValidation }) {
  const rows = [...rowsFor(validation.acquirer), ...rowsFor(validation.target)].sort(
    (a, b) =>
      ['Blocking', 'Warning', 'Pass'].indexOf(a.severity) -
      ['Blocking', 'Warning', 'Pass'].indexOf(b.severity),
  )
  const blocking = rows.filter((r) => r.severity === 'Blocking').length
  const warnings = rows.filter((r) => r.severity === 'Warning').length
  const clean = [validation.acquirer, validation.target].filter(
    (v) => rowsFor(v)[0]?.severity === 'Pass',
  ).length

  return (
    <>
      {validation.status !== 'pass' && (
        <div className={`banner ${validation.status === 'fail' ? 'error' : 'warn'}`} role="alert">
          <div className="banner-main">
            <div className="banner-title">
              {validation.status === 'fail'
                ? `Validation failed — ${blocking} blocking issue${blocking === 1 ? '' : 's'}, ${warnings} warning${warnings === 1 ? '' : 's'}`
                : `Validation degraded — ${warnings} warning${warnings === 1 ? '' : 's'}`}
            </div>
            <div className="banner-sub">
              {validation.status === 'fail'
                ? 'Generation is disabled until the blocking issues are resolved. Warnings can be accepted; they are carried into the workbook provenance.'
                : 'Warnings can be accepted; they are carried into the workbook provenance and flagged in the Excel model.'}
            </div>
          </div>
        </div>
      )}

      <section className="tile validation-tile">
        <div className="tile-head">
          <h2>Data validation log</h2>
          <span className={`status-pill ${validation.status}`}>
            Combined: {validation.status.toUpperCase()}
          </span>
        </div>
        <table className="deck-table">
          <thead>
            <tr>
              <th style={{ width: 90 }}>Severity</th>
              <th style={{ width: 90 }}>Company</th>
              <th>Finding</th>
              <th style={{ width: 130 }}>Category</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <span className={badgeClass[r.severity]}>{r.severity}</span>
                </td>
                <td style={{ fontWeight: 600, color: 'var(--ink)' }}>{r.company}</td>
                <td style={{ color: 'var(--ink-2)' }}>{r.finding}</td>
                <td>{r.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="validation-counters">
          <div className="validation-counter">
            <div className="vc-label">Blocking</div>
            <div className={`vc-fig ${blocking > 0 ? 'negative' : ''}`}>{blocking}</div>
            <div className="vc-sub negative-note">
              {blocking > 0 ? 'Cannot model until resolved' : '—'}
            </div>
          </div>
          <div className="validation-counter">
            <div className="vc-label">Warnings</div>
            <div className={`vc-fig ${warnings > 0 ? '' : ''}`}>{warnings}</div>
            <div className="vc-sub warning-note">
              {warnings > 0 ? 'Carried to provenance sheet' : '—'}
            </div>
          </div>
          <div className="validation-counter">
            <div className="vc-label">Companies clean</div>
            <div className="vc-fig">{clean}/2</div>
            <div className="vc-sub positive-note">Direct from XBRL</div>
          </div>
        </div>
      </section>
    </>
  )
}
