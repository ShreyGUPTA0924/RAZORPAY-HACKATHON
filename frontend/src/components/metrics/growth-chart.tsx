import { ArrowRight } from 'lucide-react'
import { type GrowthMetric, growthMeta } from '@/data/results'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function MetricBar({ metric }: { metric: GrowthMetric }) {
  const improved =
    metric.betterWhen === 'higher' ? metric.after > metric.before : metric.after < metric.before
  const delta = metric.after - metric.before

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <p className="text-body-sm font-medium text-foreground">{metric.label}</p>
        <p className={cn('text-caption font-semibold tabular-nums', improved ? 'text-success' : 'text-danger')}>
          {delta > 0 ? '+' : ''}
          {delta}pp
        </p>
      </div>
      <p className="text-caption text-muted-foreground">{metric.description}</p>

      <div className="flex items-center gap-3">
        <div className="flex flex-1 items-center gap-2">
          <span className="w-20 shrink-0 text-caption text-muted-foreground">Raw catalog</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-neutral-400 dark:bg-neutral-600" style={{ width: `${metric.before}%` }} />
          </div>
          <span className="w-10 shrink-0 text-right text-caption tabular-nums text-muted-foreground">{metric.before}%</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex flex-1 items-center gap-2">
          <span className="w-20 shrink-0 text-caption font-medium text-foreground">AgentFront</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={cn('h-full rounded-full transition-all duration-700', improved ? 'bg-success' : 'bg-danger')}
              style={{ width: `${metric.after}%` }}
            />
          </div>
          <span className="w-10 shrink-0 text-right text-caption font-semibold tabular-nums text-foreground">
            {metric.after}%
          </span>
        </div>
      </div>
    </div>
  )
}

export function GrowthChart({ metrics }: { metrics: GrowthMetric[] }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2 text-body-sm font-medium text-foreground">
          Raw catalog
          <ArrowRight className="size-3.5 text-muted-foreground" />
          Generated AgentFront surface
        </div>
        <p className="text-caption text-muted-foreground">
          Same scripted buyer agent, same {growthMeta.nIntents} purchase intents (seed {growthMeta.seed}), run twice
          against the {growthMeta.nSkus}-SKU catalog.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {metrics.map((m) => (
          <MetricBar key={m.label} metric={m} />
        ))}
      </CardContent>
    </Card>
  )
}
