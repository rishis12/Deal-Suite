import type { CompanyVerdict, PairValidation } from '../types'

function statusClass(status: string): string {
  if (status === 'pass') return 'status-pill pass'
  if (status === 'degraded') return 'status-pill degraded'
  return 'status-pill fail'
}

function VerdictBlock({ verdict, role }: { verdict: CompanyVerdict; role: string }) {
  return (
    <div className="verdict-block">
      <div className="verdict-head">
        <span className="verdict-role">{role}</span>
        <span className="verdict-ticker">{verdict.ticker}</span>
        <span className={statusClass(verdict.status)}>{verdict.status.toUpperCase()}</span>
      </div>
      {verdict.sectorExcluded && verdict.sectorExcludedReason && (
        <p className="verdict-item negative-note">✕ {verdict.sectorExcludedReason}</p>
      )}
      {verdict.disqualifyingReasons
        .filter((r) => r !== verdict.sectorExcludedReason)
        .map((r, i) => (
          <p key={`d${i}`} className="verdict-item negative-note">
            ✕ {r}
          </p>
        ))}
      {verdict.missingHard.map((m, i) => (
        <p key={`h${i}`} className="verdict-item warning-note">
          ! {m}
        </p>
      ))}
      {verdict.missingSoft.map((m, i) => (
        <p key={`s${i}`} className="verdict-item muted-note">
          ◦ {m}
        </p>
      ))}
      {verdict.defaultsApplied.map((m, i) => (
        <p key={`df${i}`} className="verdict-item defaulted-note">
          → {m}
        </p>
      ))}
      {verdict.warnings.map((m, i) => (
        <p key={`w${i}`} className="verdict-item warning-note">
          ⚠ {m}
        </p>
      ))}
      {verdict.substituteWarnings.map((m, i) => (
        <p key={`sub${i}`} className="verdict-item substituted-note">
          ~ {m}
        </p>
      ))}
      {verdict.status === 'pass' &&
        verdict.missingSoft.length === 0 &&
        verdict.warnings.length === 0 &&
        verdict.substituteWarnings.length === 0 && (
          <p className="verdict-item positive-note">✓ All required data present.</p>
        )}
    </div>
  )
}

export function ValidationPanel({ validation }: { validation: PairValidation }) {
  return (
    <section className="tile validation-tile">
      <div className="tile-head">
        <h2>Validation</h2>
        <span className={statusClass(validation.status)}>
          Combined: {validation.status.toUpperCase()}
        </span>
      </div>
      {validation.status === 'fail' && (
        <p className="negative-note">
          This pair cannot be modeled. See the per-company reasons below.
        </p>
      )}
      <div className="verdict-grid">
        <VerdictBlock verdict={validation.acquirer} role="Acquirer" />
        <VerdictBlock verdict={validation.target} role="Target" />
      </div>
    </section>
  )
}
