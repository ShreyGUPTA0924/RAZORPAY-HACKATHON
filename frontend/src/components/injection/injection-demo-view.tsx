import { AlertOctagon, ArrowRight, Check, FileWarning, Loader2, ShieldAlert, Sparkles, Split } from 'lucide-react'
import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { CACHED_INJECTION_DEMO_RESULT, INJECTION_MARKER_START } from '@/data/injection-demo'
import { type ApiResult, type InjectionDemoResult, runInjectionDemo } from '@/lib/api-client'
import { cn } from '@/lib/utils'

const PANEL_DELAY_MS = 700
// The disagreement panel is the climax -- give it extra beat before it lands.
const CLIMAX_DELAY_MS = 1100

function PoisonedTextBlock({ title, description }: { title: string; description: string }) {
  const markerIndex = description.indexOf(INJECTION_MARKER_START)
  const before = markerIndex >= 0 ? description.slice(0, markerIndex) : description
  const injected = markerIndex >= 0 ? description.slice(markerIndex) : ''
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-4 font-mono text-caption leading-relaxed">
      <p className="mb-2 text-foreground">
        <span className="text-muted-foreground">title: </span>
        {title}
      </p>
      <p className="text-foreground">
        <span className="text-muted-foreground">description: </span>
        {before}
        {injected && (
          <mark className="rounded bg-danger-subtle px-1 py-0.5 text-danger decoration-danger">{injected}</mark>
        )}
      </p>
    </div>
  )
}

function PanelShell({ step, title, icon, children }: { step: number; title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="animate-slide-up">
      <CardHeader className="flex-row items-center gap-3 space-y-0 pb-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-caption font-semibold text-accent-foreground">
          {step}
        </div>
        <div className="flex items-center gap-2 text-body font-semibold text-foreground">
          {icon}
          {title}
        </div>
      </CardHeader>
      <CardContent className="pt-0">{children}</CardContent>
    </Card>
  )
}

export function InjectionDemoView() {
  const [running, setRunning] = React.useState(false)
  const [outcome, setOutcome] = React.useState<ApiResult<InjectionDemoResult> | null>(null)
  const [revealStep, setRevealStep] = React.useState(0)

  React.useEffect(() => {
    if (!outcome || revealStep >= 4) return
    const delay = revealStep === 2 ? CLIMAX_DELAY_MS : PANEL_DELAY_MS
    const id = window.setTimeout(() => setRevealStep((s) => s + 1), delay)
    return () => window.clearTimeout(id)
  }, [outcome, revealStep])

  async function run() {
    setRunning(true)
    setOutcome(null)
    setRevealStep(0)
    const result = await runInjectionDemo(CACHED_INJECTION_DEMO_RESULT)
    setOutcome(result)
    setRunning(false)
    setRevealStep(1)
  }

  const data = outcome?.data

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4 space-y-0 pb-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <FileWarning className="size-5" />
            </div>
            <div>
              <p className="text-heading-sm text-foreground">Catalog injection demo</p>
              <p className="text-body-sm text-muted-foreground">
                A real listing description with an injected instruction telling the extractor to relabel the
                product. Runs the actual extraction pipeline live, then the mandatory title-only cross-check that
                catches it — <code className="font-mono text-caption">pipeline/extract.py</code>.
              </p>
            </div>
          </div>
          {outcome && (
            <Badge variant={outcome.cached ? 'secondary' : 'success'} className="shrink-0 whitespace-nowrap">
              {outcome.cached ? 'Cached' : 'Live'}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <Button onClick={run} disabled={running} className="gap-2">
            {running ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Extracting…
              </>
            ) : (
              <>
                <Sparkles className="size-4" />
                {outcome ? 'Run again' : 'Run injection demo'}
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {data && (
        <div className="flex flex-col gap-4">
          {revealStep >= 1 && (
            <PanelShell step={1} title="Poisoned input" icon={<FileWarning className="size-4 text-danger" />}>
              <PoisonedTextBlock title={data.title} description={data.poisoned_description} />
            </PanelShell>
          )}

          {revealStep >= 2 && (
            <PanelShell step={2} title="Primary extraction" icon={<Check className="size-4 text-success" />}>
              <div className="flex items-center gap-4 rounded-lg border border-success/30 bg-success-subtle px-4 py-3.5">
                <div>
                  <p className="font-mono text-heading text-foreground">{data.primary_value}</p>
                  <p className="text-caption text-muted-foreground">accessory_type, as reported by the primary extraction call</p>
                </div>
                <div className="ml-auto flex items-center gap-1.5 text-success">
                  <Check className="size-4" />
                  <span className="text-heading-sm tabular-nums">{Math.round(data.primary_confidence * 100)}%</span>
                </div>
              </div>
              <p className="mt-2 text-caption text-muted-foreground">
                Confidently wrong: the model read the injected instruction as legitimate product text and reported
                near-total confidence in a relabeling that isn't true.
              </p>
            </PanelShell>
          )}

          {revealStep >= 3 && (
            <PanelShell step={3} title="Title-only cross-check" icon={<Split className="size-4 text-warning" />}>
              <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
                <div className="rounded-lg border border-border px-4 py-3.5 text-center">
                  <p className="text-caption text-muted-foreground">Primary (full text)</p>
                  <p className="mt-1 font-mono text-heading-sm text-foreground">{data.primary_value}</p>
                  <p className="text-caption tabular-nums text-muted-foreground">{Math.round(data.primary_confidence * 100)}%</p>
                </div>
                <div className="flex flex-col items-center gap-1 py-2">
                  <span className="text-display font-bold leading-none text-danger">≠</span>
                  <Badge variant="danger" className="whitespace-nowrap">
                    disagreement detected
                  </Badge>
                </div>
                <div className="rounded-lg border-2 border-warning bg-warning-subtle px-4 py-3.5 text-center">
                  <p className="text-caption text-warning">Title-only (blind re-derivation)</p>
                  <p className="mt-1 font-mono text-heading-sm text-foreground">{data.title_only_value}</p>
                  <p className="text-caption tabular-nums text-warning">{Math.round(data.title_only_confidence * 100)}%</p>
                </div>
              </div>
              <p className="mt-3 text-caption text-muted-foreground">
                A mandatory second pass reads only the listing title — no description, blind to whatever the
                primary call already produced — and independently re-derives the value. It disagrees.
              </p>
            </PanelShell>
          )}

          {revealStep >= 4 && (
            <PanelShell step={4} title="Quarantine verdict" icon={<ShieldAlert className="size-4 text-danger" />}>
              <div className={cn('rounded-xl border-2 border-danger bg-danger-subtle p-5', revealStep === 4 && 'animate-slide-up')}>
                <div className="flex items-center gap-2 text-danger">
                  <AlertOctagon className="size-5" />
                  <span className="text-label uppercase tracking-wide">Quarantined</span>
                </div>
                <div className="mt-2 flex items-center gap-2 text-body-sm text-foreground">
                  <span className="font-mono">confidence {Math.round(data.primary_confidence * 100)}%</span>
                  <ArrowRight className="size-3.5 text-danger" />
                  <span className="font-mono font-semibold text-danger">confidence {Math.round(data.final_confidence * 100)}%</span>
                  <span className="text-caption text-muted-foreground">(hard-dropped on disagreement)</span>
                </div>
                {data.quarantine_reason && (
                  <p className="mt-2 text-body-sm leading-relaxed text-foreground">{data.quarantine_reason}</p>
                )}
                <p className="mt-3 font-mono text-caption text-danger/80">
                  caught by: pipeline/extract.py — mandatory title-only cross-check
                </p>
              </div>
            </PanelShell>
          )}
        </div>
      )}
    </div>
  )
}
