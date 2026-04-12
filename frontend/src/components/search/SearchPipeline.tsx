import { motion } from 'framer-motion'
import type { PipelineStep } from '../../types/search'
import { cn } from '../../utils/cn'

const STEP_ICONS: Record<string, string> = {
  intent_parsing: '🎯',
  xhs_search: '📖',
  comment_analysis: '💬',
  cross_validation: '✅',
  poi_enrichment: '📍',
  result_generation: '🍽',
}

function StepIcon({ step }: { step: PipelineStep }) {
  if (step.status === 'loading') {
    return (
      <div className="w-6 h-6 rounded-full border-2 border-ember border-t-transparent animate-spin" />
    )
  }
  if (step.status === 'done') {
    return (
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        className="w-6 h-6 rounded-full bg-emerald-100 flex items-center justify-center"
      >
        <span className="text-emerald-600 text-xs">✓</span>
      </motion.div>
    )
  }
  if (step.status === 'error') {
    return (
      <div className="w-6 h-6 rounded-full bg-red-100 flex items-center justify-center">
        <span className="text-red-500 text-xs">✗</span>
      </div>
    )
  }
  return (
    <div className="w-6 h-6 rounded-full bg-stone-100 flex items-center justify-center">
      <span className="text-xs">{STEP_ICONS[step.id] || '○'}</span>
    </div>
  )
}

export function SearchPipeline({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="py-2 space-y-0">
      {steps.map((step, i) => (
        <motion.div
          key={step.id}
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.06 }}
          className="flex items-center gap-3 py-1.5"
        >
          <div className="relative flex flex-col items-center">
            <StepIcon step={step} />
            {i < steps.length - 1 && (
              <div className={cn(
                'w-px h-4 mt-0.5',
                step.status === 'done' ? 'bg-emerald-200' : 'bg-stone-200'
              )} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className={cn(
              'text-xs leading-tight',
              step.status === 'loading' ? 'text-ember font-medium' :
              step.status === 'done' ? 'text-ink-light' :
              step.status === 'error' ? 'text-red-500' :
              'text-muted'
            )}>
              {step.label}
            </p>
            {step.detail && step.status !== 'pending' && (
              <p className="text-[10px] text-muted truncate">{step.detail}</p>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  )
}
