import { AlertTriangle, Check, Minus } from 'lucide-react'
import type { AttrValue } from '@/data/catalog'
import { cn } from '@/lib/utils'

// Mirrors pipeline/quarantine.py's real CONFIDENCE_THRESHOLD (0.5): below
// it, the field is redacted, not published, regardless of what value the
// model proposed. The 0.7 split above that is a display-only distinction
// (confident vs. borderline-but-published) -- quarantine.py itself only
// has the one real threshold.
const REDACT_THRESHOLD = 0.5
const CONFIDENT_THRESHOLD = 0.7

export function ConfidenceBadge({ attr, redacted }: { attr: AttrValue; redacted: boolean }) {
  if (attr.value === null || attr.value === undefined) {
    return (
      <span className="inline-flex items-center gap-1 text-caption text-muted-foreground/70">
        <Minus className="size-3" />
        not found
      </span>
    )
  }

  const belowThreshold = attr.confidence < REDACT_THRESHOLD
  const isConfident = attr.confidence >= CONFIDENT_THRESHOLD

  if (redacted || belowThreshold) {
    return (
      <span className="inline-flex items-center gap-1 text-caption font-medium text-danger">
        <AlertTriangle className="size-3" />
        {Math.round(attr.confidence * 100)}% · redacted
      </span>
    )
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-caption font-medium',
        isConfident ? 'text-success' : 'text-warning'
      )}
    >
      {isConfident && <Check className="size-3" />}
      {Math.round(attr.confidence * 100)}%
    </span>
  )
}
