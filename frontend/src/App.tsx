import { Construction } from 'lucide-react'
import * as React from 'react'
import { AppShell } from '@/components/layout/app-shell'
import type { Step } from '@/components/layout/stepper'
import { ThemeProvider } from '@/components/layout/theme-provider'
import { ExtractionView } from '@/components/extraction/extraction-view'
import { TooltipProvider } from '@/components/ui/tooltip'

const STEPS: Step[] = [
  { id: 'extraction', label: 'Extraction', description: 'Messy catalog → structured' },
  { id: 'surface', label: 'Surface', description: 'Browsable, verified catalog' },
  { id: 'agent', label: 'Agent mode', description: 'Live MCP transaction' },
  { id: 'results', label: 'Results', description: 'Growth & adversarial' },
]

function ComingSoon({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-24 text-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Construction className="size-5" />
      </div>
      <p className="text-body-sm text-muted-foreground">{label} — next in this build.</p>
    </div>
  )
}

function AppContent() {
  const [activeStep, setActiveStep] = React.useState('extraction')
  const [completed, setCompleted] = React.useState<Set<string>>(new Set())

  function markComplete(id: string) {
    setCompleted((prev) => new Set(prev).add(id))
  }

  return (
    <AppShell steps={STEPS} activeStepId={activeStep} completedStepIds={completed} onSelectStep={setActiveStep}>
      {activeStep === 'extraction' && <ExtractionView onComplete={() => markComplete('extraction')} />}
      {activeStep === 'surface' && <ComingSoon label="Browsable surface with compatibility relationships" />}
      {activeStep === 'agent' && <ComingSoon label="Split-view live MCP tool-call stream" />}
      {activeStep === 'results' && <ComingSoon label="Growth A/B + adversarial dashboard" />}
    </AppShell>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={150}>
        <AppContent />
      </TooltipProvider>
    </ThemeProvider>
  )
}
