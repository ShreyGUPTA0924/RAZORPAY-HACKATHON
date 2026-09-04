import { Ban, Clock, KeyRound, Layers, Loader2, Repeat2, Swords, Tags, XCircle, Zap } from 'lucide-react'
import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { type AttackIcon, CAUGHT_BY_CODE, CAUGHT_BY_IDEMPOTENCY, type RefusalScenarioDef } from '@/data/refusal-scenarios'
import { type ApiResult, type ScenarioResult, runRefusalScenario } from '@/lib/api-client'
import { cn } from '@/lib/utils'

const ICONS: Record<AttackIcon, typeof Ban> = {
  ceiling: Ban,
  cumulative: Layers,
  expiry: Clock,
  replay: Repeat2,
  category: Tags,
  retry: Zap,
  signature: KeyRound,
}

function caughtByFor(step: ScenarioResult['steps'][number]): string | null {
  if (step.refusal_code) return CAUGHT_BY_CODE[step.refusal_code] ?? null
  if (step.decision === 'blocked') return CAUGHT_BY_IDEMPOTENCY
  return null
}

function StepRow({ step }: { step: ScenarioResult['steps'][number] }) {
  const blocked = step.decision === 'refuse' || step.decision === 'blocked'
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <Badge variant={blocked ? 'danger' : 'success'} className="mt-0.5 shrink-0 whitespace-nowrap">
        {step.decision}
      </Badge>
      <div className="min-w-0">
        <p className="text-caption text-foreground">{step.label}</p>
        {step.refusal_detail && <p className="text-caption text-muted-foreground">{step.refusal_detail}</p>}
      </div>
    </div>
  )
}

export function AttackCard({ scenario }: { scenario: RefusalScenarioDef }) {
  const [running, setRunning] = React.useState(false)
  const [result, setResult] = React.useState<ApiResult<ScenarioResult> | null>(null)
  const Icon = ICONS[scenario.icon]

  async function runAttack() {
    setRunning(true)
    const outcome = await runRefusalScenario(scenario.id, scenario.cachedResult)
    setResult(outcome)
    setRunning(false)
  }

  const steps = result?.data.steps ?? []
  const heroStep = steps.find((s) => s.decision === 'refuse') ?? steps.find((s) => s.decision === 'blocked') ?? steps.at(-1) ?? null
  const caughtBy = heroStep ? caughtByFor(heroStep) : null

  return (
    <Card className={cn('flex flex-col', result && 'ring-1 ring-danger/30')}>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <Icon className="size-5" />
          </div>
          <div>
            <p className="text-body font-semibold text-foreground">{scenario.title}</p>
            <p className="text-caption text-muted-foreground">{scenario.narrative}</p>
          </div>
        </div>
        {result && (
          <Badge variant={result.cached ? 'secondary' : 'success'} className="shrink-0 whitespace-nowrap">
            {result.cached ? 'Cached' : 'Live'}
          </Badge>
        )}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        {!result && (
          <Button onClick={runAttack} disabled={running} className="gap-2 self-start">
            {running ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Running attack…
              </>
            ) : (
              <>
                <Swords className="size-4" />
                Run attack
              </>
            )}
          </Button>
        )}

        {result && heroStep && (
          <>
            {/* the refusal itself is the visual hero, not a footnote */}
            <div className="animate-slide-up rounded-xl border-2 border-danger bg-danger-subtle p-5">
              <div className="flex items-center gap-2 text-danger">
                <XCircle className="size-5" />
                <span className="text-label uppercase tracking-wide">
                  {heroStep.decision === 'blocked' ? 'Blocked' : 'Refused'}
                </span>
              </div>
              {heroStep.refusal_code && (
                <p className="mt-2 break-words font-mono text-heading-sm leading-snug text-danger [word-break:break-word]">
                  {heroStep.refusal_code}
                </p>
              )}
              {heroStep.refusal_detail && (
                <p className="mt-2 text-body-sm leading-relaxed text-foreground">{heroStep.refusal_detail}</p>
              )}
              {caughtBy && (
                <p className="mt-3 font-mono text-caption text-danger/80">caught by: {caughtBy}</p>
              )}
            </div>

            {steps.length > 1 && (
              <>
                <Separator />
                <div>
                  <p className="mb-1 text-caption font-medium text-muted-foreground">Full sequence</p>
                  <div className="flex flex-col divide-y divide-border">
                    {steps.map((step, i) => (
                      <StepRow key={i} step={step} />
                    ))}
                  </div>
                </div>
              </>
            )}

            <Button onClick={runAttack} variant="outline" size="sm" disabled={running} className="gap-2 self-start">
              {running ? <Loader2 className="size-3.5 animate-spin" /> : <Swords className="size-3.5" />}
              Run again
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  )
}
