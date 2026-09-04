import { AdversarialPanel } from '@/components/metrics/adversarial-panel'
import { GrowthChart } from '@/components/metrics/growth-chart'
import { growthMetrics } from '@/data/results'

export function ResultsView() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-heading text-foreground">Growth &amp; adversarial results</h2>
        <p className="text-body-sm text-muted-foreground">
          Real numbers from committed runs — eval/growth_ab_results.json and
          eval/adversarial/adversarial_results.json.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="xl:col-span-2">
          <GrowthChart metrics={growthMetrics} />
        </div>
        <div className="xl:col-span-3">
          <AdversarialPanel />
        </div>
      </div>
    </div>
  )
}
