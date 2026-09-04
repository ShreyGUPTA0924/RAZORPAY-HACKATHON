import { AlertCircle, CheckCircle2, ShieldCheck, Wrench } from 'lucide-react'
import { type AdversarialFinding, adversarialFindings, adversarialMeta } from '@/data/results'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

const STATUS_META: Record<AdversarialFinding['status'], { icon: typeof Wrench; label: string; variant: 'danger' | 'success' | 'warning' }> = {
  confirmed_fixed: { icon: Wrench, label: 'Found & fixed', variant: 'danger' },
  defended: { icon: ShieldCheck, label: 'Defended', variant: 'success' },
  off_target: { icon: AlertCircle, label: 'Off-target finding', variant: 'warning' },
}

export function AdversarialPanel() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <p className="text-body-sm font-medium text-foreground">Independent adversarial red-team</p>
        <p className="text-caption text-muted-foreground">
          {adversarialMeta.attackerModel} — shown ONLY the black-box MCP surface and the goal, no sight of gate.py /
          refusal.py / mandate.py's logic. Attacking {adversarialMeta.extractorModel}'s extraction.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-muted px-3 py-2.5 text-center">
            <p className="text-heading tabular-nums text-foreground">{adversarialMeta.totalAttacks}</p>
            <p className="text-caption text-muted-foreground">total attacks</p>
          </div>
          <div className="rounded-lg bg-muted px-3 py-2.5 text-center">
            <p className="text-heading tabular-nums text-foreground">{adversarialMeta.mandateAttacks}</p>
            <p className="text-caption text-muted-foreground">mandate / gate</p>
          </div>
          <div className="rounded-lg bg-muted px-3 py-2.5 text-center">
            <p className="text-heading tabular-nums text-foreground">{adversarialMeta.catalogInjectionAttacks}</p>
            <p className="text-caption text-muted-foreground">catalog injection</p>
          </div>
        </div>

        <Separator />

        <div className="flex items-start gap-2 rounded-lg bg-accent/50 px-3.5 py-2.5 text-caption text-accent-foreground">
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
          <p>
            A clean 100% isn't the credible result — here's what got through, and what didn't. Every finding below
            was manually verified against the real code and real catalog text, not just the attacker's own claim.
          </p>
        </div>

        <div className="flex flex-col gap-3">
          {adversarialFindings.map((finding) => {
            const meta = STATUS_META[finding.status]
            const Icon = meta.icon
            return (
              <div key={finding.name} className="flex gap-3 rounded-lg border border-border p-3.5">
                <div className="mt-0.5">
                  <Badge variant={meta.variant} className="whitespace-nowrap">
                    <Icon className="size-3" />
                    {meta.label}
                  </Badge>
                </div>
                <div className="min-w-0">
                  <p className="text-body-sm font-medium text-foreground">{finding.name}</p>
                  <p className="mt-0.5 text-caption leading-relaxed text-muted-foreground">{finding.summary}</p>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
