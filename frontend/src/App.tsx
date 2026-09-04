import * as React from 'react'
import { AgentView } from '@/components/agent/agent-view'
import { SurfaceView } from '@/components/catalog/surface-view'
import { ExtractionView } from '@/components/extraction/extraction-view'
import { InjectionDemoView } from '@/components/injection/injection-demo-view'
import { AppShell } from '@/components/layout/app-shell'
import type { Step } from '@/components/layout/stepper'
import { ThemeProvider } from '@/components/layout/theme-provider'
import { ResultsView } from '@/components/metrics/results-view'
import { RefusalGalleryView } from '@/components/refusals/refusal-gallery-view'
import { TooltipProvider } from '@/components/ui/tooltip'

const STEPS: Step[] = [
  { id: 'extraction', label: 'Extraction', description: 'Messy catalog → structured' },
  { id: 'surface', label: 'Surface', description: 'Browsable, verified catalog' },
  { id: 'agent', label: 'Agent mode', description: 'Scripted MCP transaction' },
  { id: 'refusals', label: 'Refusal gallery', description: 'Live attacks, real refusals' },
  { id: 'injection', label: 'Injection demo', description: 'Poisoned catalog text, live' },
  { id: 'results', label: 'Results', description: 'Growth & adversarial' },
]

function AppContent() {
  const [activeStep, setActiveStep] = React.useState('extraction')
  const [completed, setCompleted] = React.useState<Set<string>>(new Set())

  function markComplete(id: string) {
    setCompleted((prev) => new Set(prev).add(id))
  }

  return (
    <AppShell steps={STEPS} activeStepId={activeStep} completedStepIds={completed} onSelectStep={setActiveStep}>
      {activeStep === 'extraction' && <ExtractionView onComplete={() => markComplete('extraction')} />}
      {activeStep === 'surface' && <SurfaceView />}
      {activeStep === 'agent' && <AgentView />}
      {activeStep === 'refusals' && <RefusalGalleryView />}
      {activeStep === 'injection' && <InjectionDemoView />}
      {activeStep === 'results' && <ResultsView />}
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
