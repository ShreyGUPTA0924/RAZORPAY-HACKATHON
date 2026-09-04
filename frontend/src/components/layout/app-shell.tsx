import type * as React from 'react'
import { LogoMark } from '@/components/layout/logo-mark'
import { type Step, Stepper } from '@/components/layout/stepper'
import { ThemeToggle } from '@/components/layout/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { useBackendMode } from '@/hooks/use-backend-mode'

interface AppShellProps {
  steps: Step[]
  activeStepId: string
  completedStepIds: Set<string>
  onSelectStep: (id: string) => void
  children: React.ReactNode
}

export function AppShell({ steps, activeStepId, completedStepIds, onSelectStep, children }: AppShellProps) {
  const backendLive = useBackendMode()

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-md">
        <div className="container flex h-16 items-center justify-between gap-6">
          <div className="flex items-center gap-2.5">
            <LogoMark className="h-8 w-8" />
            <div className="flex flex-col leading-none">
              <span className="text-heading-sm font-semibold tracking-tight text-foreground">AgentFront</span>
              <span className="text-label uppercase text-muted-foreground">Merchant Agent-Readiness Engine</span>
            </div>
          </div>

          <div className="hidden items-center gap-2 lg:flex">
            {backendLive ? (
              <Badge variant="success">Live backend</Badge>
            ) : (
              <Badge variant="secondary">Cached replay</Badge>
            )}
            <Badge variant="secondary">Razorpay test mode</Badge>
          </div>

          <ThemeToggle />
        </div>
      </header>

      <div className="border-b border-border bg-card/50">
        <div className="container py-4">
          <Stepper steps={steps} activeId={activeStepId} completedIds={completedStepIds} onSelect={onSelectStep} />
        </div>
      </div>

      <main className="container py-8">{children}</main>
    </div>
  )
}
