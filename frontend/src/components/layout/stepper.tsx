import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Step {
  id: string
  label: string
  description: string
}

interface StepperProps {
  steps: Step[]
  activeId: string
  completedIds: Set<string>
  onSelect: (id: string) => void
}

export function Stepper({ steps, activeId, completedIds, onSelect }: StepperProps) {
  return (
    <nav aria-label="Demo flow" className="w-full">
      <ol className="flex items-stretch">
        {steps.map((step, i) => {
          const isActive = step.id === activeId
          const isCompleted = completedIds.has(step.id)
          const isLast = i === steps.length - 1

          return (
            <li key={step.id} className={cn('flex items-center', !isLast && 'flex-1')}>
              <button
                type="button"
                onClick={() => onSelect(step.id)}
                className="group flex items-center gap-3 rounded-lg py-2 pr-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span
                  className={cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-body-sm font-semibold transition-all duration-200',
                    isActive &&
                      'border-primary bg-primary text-primary-foreground shadow-glow-brand',
                    isCompleted &&
                      !isActive &&
                      'border-success/40 bg-success-subtle text-success',
                    !isActive &&
                      !isCompleted &&
                      'border-border bg-muted text-muted-foreground group-hover:border-neutral-400 dark:group-hover:border-neutral-600'
                  )}
                >
                  {isCompleted && !isActive ? <Check className="size-4" /> : i + 1}
                </span>
                <span className="hidden sm:flex flex-col">
                  <span
                    className={cn(
                      'text-body-sm font-medium leading-tight transition-colors',
                      isActive ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground'
                    )}
                  >
                    {step.label}
                  </span>
                  <span className="text-caption text-muted-foreground/80 leading-tight">{step.description}</span>
                </span>
              </button>
              {!isLast && (
                <div
                  className={cn(
                    'mx-1 h-px flex-1 min-w-4 transition-colors duration-300',
                    isCompleted ? 'bg-success/40' : 'bg-border'
                  )}
                />
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
