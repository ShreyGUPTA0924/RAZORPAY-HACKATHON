import { ShieldAlert } from 'lucide-react'
import { AttackCard } from '@/components/refusals/attack-card'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { refusalScenarios } from '@/data/refusal-scenarios'

export function RefusalGalleryView() {
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0 pb-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <ShieldAlert className="size-5" />
          </div>
          <div>
            <p className="text-heading-sm text-foreground">Refusal gallery</p>
            <p className="text-body-sm text-muted-foreground">
              Seven ways a buyer agent can misbehave. Each card runs a real, freshly-signed mandate through the
              actual <code className="font-mono text-caption">surface/gate.py</code> /{' '}
              <code className="font-mono text-caption">surface/mandate.py</code> /{' '}
              <code className="font-mono text-caption">surface/idempotency.py</code> stack against real Redis via
              the API layer — nothing here is a mocked response. If the backend isn't reachable, the card falls
              back to a real, previously-captured run of the same scenario and says so.
            </p>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-caption text-muted-foreground">
            A new random intent, nonce, and mandate id are used on every click, so repeated runs never collide with
            earlier state.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {refusalScenarios.map((scenario) => (
          <AttackCard key={scenario.id} scenario={scenario} />
        ))}
      </div>
    </div>
  )
}
