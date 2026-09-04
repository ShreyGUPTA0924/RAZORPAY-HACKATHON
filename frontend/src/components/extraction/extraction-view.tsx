import { CheckCircle2, FileSpreadsheet, Loader2, ShieldAlert, Sparkles } from 'lucide-react'
import * as React from 'react'
import { SkuRow } from '@/components/extraction/sku-row'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { catalogSample } from '@/data/catalog'
import { cn } from '@/lib/utils'

const REVEAL_INTERVAL_MS = 260

interface StatProps {
  label: string
  value: number
  icon: React.ReactNode
  tone?: 'default' | 'success' | 'danger'
}

function Stat({ label, value, icon, tone = 'default' }: StatProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <div
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-md',
          tone === 'success' && 'bg-success-subtle text-success',
          tone === 'danger' && 'bg-danger-subtle text-danger',
          tone === 'default' && 'bg-accent text-accent-foreground'
        )}
      >
        {icon}
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-heading tabular-nums text-foreground">{value}</span>
        <span className="text-caption text-muted-foreground">{label}</span>
      </div>
    </div>
  )
}

export function ExtractionView({ onComplete }: { onComplete?: () => void }) {
  const total = catalogSample.length
  const [revealedCount, setRevealedCount] = React.useState(0)
  const [running, setRunning] = React.useState(false)
  const [started, setStarted] = React.useState(false)

  React.useEffect(() => {
    if (!running || revealedCount >= total) return
    const id = window.setTimeout(() => setRevealedCount((c) => c + 1), REVEAL_INTERVAL_MS)
    return () => window.clearTimeout(id)
  }, [running, revealedCount, total])

  React.useEffect(() => {
    if (revealedCount === total && total > 0 && started) {
      onComplete?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revealedCount, total, started])

  const revealed = catalogSample.slice(0, revealedCount)
  const publishedCount = revealed.filter((r) => r.published).length
  const quarantinedCount = revealed.filter((r) => !r.published).length
  const isProcessing = running && revealedCount < total
  const isDone = started && revealedCount === total

  function start() {
    setStarted(true)
    setRunning(true)
    setRevealedCount(0)
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <FileSpreadsheet className="size-5" />
            </div>
            <div>
              <p className="text-heading-sm text-foreground">data/catalog.json</p>
              <p className="text-body-sm text-muted-foreground">
                60-SKU messy Flipkart phone-accessories export · inconsistent titles, no structured attributes
              </p>
            </div>
          </div>
          <Button onClick={start} disabled={isProcessing} size="lg" className="gap-2">
            {isProcessing ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Extracting…
              </>
            ) : (
              <>
                <Sparkles className="size-4" />
                {started ? 'Re-run extraction' : 'Run extraction'}
              </>
            )}
          </Button>
        </CardHeader>
        {started && (
          <CardContent className="pt-0">
            <div className="flex items-center gap-3">
              <Progress value={(revealedCount / total) * 100} className="h-2" />
              <span className="w-16 shrink-0 text-right text-caption tabular-nums text-muted-foreground">
                {revealedCount}/{total}
              </span>
            </div>
          </CardContent>
        )}
      </Card>

      {started && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 animate-fade-in">
          <Stat label="SKUs processed" value={revealedCount} icon={<Sparkles className="size-4.5" />} />
          <Stat label="Published clean" value={publishedCount} icon={<CheckCircle2 className="size-4.5" />} tone="success" />
          <Stat label="Quarantined" value={quarantinedCount} icon={<ShieldAlert className="size-4.5" />} tone="danger" />
        </div>
      )}

      {started && (
        <Card className="animate-fade-in">
          <CardHeader className="pb-3">
            <p className="text-body-sm font-medium text-foreground">
              {isDone ? 'Extraction complete' : 'Extracting attributes, live'}
            </p>
            <p className="text-caption text-muted-foreground">
              Every value carries a confidence score. Anything below 50% is redacted at publish time, never
              guessed — see the surface tab.
            </p>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {catalogSample.map((row, i) => (
              <SkuRow key={row.skuId} row={row} revealed={i < revealedCount} />
            ))}
            {isProcessing && (
              <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-4 py-3 text-caption text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                Reading listing text and proposing attributes…
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
