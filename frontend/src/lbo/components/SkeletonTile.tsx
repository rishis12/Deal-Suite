interface Props {
  className?: string
}

export function SkeletonTile({ className = '' }: Props) {
  return (
    <div className={`skeleton ${className}`} aria-hidden>
      <div className="skeleton-line lg" />
      <div className="skeleton-line" />
      <div className="skeleton-line" />
      <div className="skeleton-line sm" />
      <div className="skeleton-line" style={{ width: '75%' }} />
    </div>
  )
}
