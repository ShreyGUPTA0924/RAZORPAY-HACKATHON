import {
  CheckCircle2,
  CreditCard,
  KeyRound,
  Loader2,
  Play,
  Search,
  ShieldCheck,
  Split,
  User,
} from 'lucide-react'
import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { type AgentStep, agentSteps, type StepActor } from '@/data/agent-session'
import { formatPaise } from '@/data/catalog'
import { cn } from '@/lib/utils'

const ACTOR_META: Record<StepActor, { icon: React.ComponentType<{ className?: string }>; label: string; tone: string }> = {
  buyer: { icon: User, label: 'Buyer agent', tone: 'bg-neutral-500/10 text-neutral-600 dark:text-neutral-400' },
  mandate: { icon: KeyRound, label: 'Mandate', tone: 'bg-brand-500/10 text-brand-600 dark:text-brand-400' },
  catalog: { icon: Search, label: 'MCP surface', tone: 'bg-accent text-accent-foreground' },
  gate: { icon: ShieldCheck, label: 'Gate', tone: 'bg-success-subtle text-success' },
  payment: { icon: CreditCard, label: 'Razorpay', tone: 'bg-warning-subtle text-warning' },
}

function TimelineStep({ step, state }: { step: AgentStep; state: 'pending' | 'active' | 'done' }) {
  const meta = ACTOR_META[step.actor]
  const Icon = meta.icon
  return (
    <div
      className={cn(
        'flex gap-3 rounded-lg border px-3.5 py-3 transition-all duration-300',
        state === 'pending' && 'border-transparent opacity-40',
        state === 'active' && 'animate-slide-up border-primary/40 bg-accent/50 shadow-soft-sm',
        state === 'done' && 'animate-slide-up border-border bg-card'
      )}
    >
      <div className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full', meta.tone)}>
        {state === 'active' ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-body-sm font-medium text-foreground">{step.title}</p>
          {state === 'done' && <CheckCircle2 className="size-3.5 shrink-0 text-success" />}
          {step.id === 'payment' && <Badge variant="warning">Simulated</Badge>}
        </div>
        <p className="mt-0.5 text-caption text-muted-foreground">{step.narrative}</p>
      </div>
    </div>
  )
}

function JsonPanel({ step }: { step: AgentStep | undefined }) {
  if (!step) {
    return (
      <div className="flex h-full items-center justify-center text-caption text-neutral-500">
        Press play to start the session…
      </div>
    )
  }
  return (
    <div key={step.id} className="animate-fade-in font-mono text-caption leading-relaxed">
      <p className="mb-2 text-neutral-500"># {step.toolCall}</p>
      {step.request !== null && (
        <>
          <p className="text-brand-400">→ request</p>
          <pre className="mb-3 whitespace-pre-wrap break-all text-neutral-300">{JSON.stringify(step.request, null, 2)}</pre>
        </>
      )}
      <p className="text-success">← response</p>
      <pre className="whitespace-pre-wrap break-all text-neutral-100">{JSON.stringify(step.response, null, 2)}</pre>
    </div>
  )
}

export function AgentView() {
  const [activeIndex, setActiveIndex] = React.useState(-1)
  const [running, setRunning] = React.useState(false)

  React.useEffect(() => {
    if (!running || activeIndex >= agentSteps.length - 1) {
      if (activeIndex >= agentSteps.length - 1) setRunning(false)
      return
    }
    const delay = agentSteps[activeIndex + 1]?.durationMs ?? 800
    const id = window.setTimeout(() => setActiveIndex((i) => i + 1), delay)
    return () => window.clearTimeout(id)
  }, [running, activeIndex])

  const started = activeIndex >= 0
  const isDone = activeIndex === agentSteps.length - 1 && !running
  const currentStep = activeIndex >= 0 ? agentSteps[activeIndex] : undefined

  function start() {
    setActiveIndex(0)
    setRunning(true)
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Split className="size-5" />
            </div>
            <div>
              <p className="text-heading-sm text-foreground">Scripted replay of a real transaction shape</p>
              <p className="text-body-sm text-muted-foreground">
                Intent Mandate → gate decision → Razorpay test-mode capture. Every request/response below matches the
                real schemas — nothing here is a live call; see the simulated label on the payment step.
              </p>
            </div>
          </div>
          <Button onClick={start} disabled={running} size="lg" className="gap-2">
            {running ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Running…
              </>
            ) : (
              <>
                <Play className="size-4" />
                {started ? 'Replay session' : 'Run session'}
              </>
            )}
          </Button>
        </CardHeader>
        {isDone && (
          <CardContent className="pt-0">
            <div className="flex flex-col gap-2 rounded-lg border border-success/30 bg-success-subtle px-4 py-3 animate-fade-in">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-4 shrink-0 text-success" />
                <p className="text-body-sm text-success">
                  Scripted result: {formatPaise(29900)} for SKU-018, mandate-verified end to end.
                </p>
              </div>
              <div className="flex items-center gap-1.5 pl-6">
                <Badge variant="warning">Simulated — not a live charge</Badge>
                <span className="text-caption text-muted-foreground">
                  Razorpay capture has only been verified for order creation; see docs/what-broke.md.
                </span>
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <p className="text-body-sm font-medium text-foreground">Agent session timeline</p>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!started && (
              <p className="rounded-lg border border-dashed border-border py-10 text-center text-body-sm text-muted-foreground">
                Run the session to see the timeline.
              </p>
            )}
            {agentSteps.map((step, i) => {
              if (i > activeIndex) return null
              const state = i === activeIndex && running ? 'active' : 'done'
              return <TimelineStep key={step.id} step={step} state={state} />
            })}
          </CardContent>
        </Card>

        <Card className="overflow-hidden !border-neutral-800 bg-neutral-950 !text-neutral-100">
          <CardHeader className="flex-row items-center gap-2 space-y-0 border-b border-neutral-800 pb-3">
            <span className="size-2.5 rounded-full bg-danger/70" />
            <span className="size-2.5 rounded-full bg-warning/70" />
            <span className="size-2.5 rounded-full bg-success/70" />
            <p className="ml-2 text-caption text-neutral-400">MCP tool-call stream</p>
            {started && <Badge variant="secondary" className="ml-auto border-neutral-700 bg-neutral-800 text-neutral-300">step {activeIndex + 1}/{agentSteps.length}</Badge>}
          </CardHeader>
          <CardContent className="h-[420px] overflow-y-auto pt-4">
            <JsonPanel step={currentStep} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
