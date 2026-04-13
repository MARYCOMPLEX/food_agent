import { motion } from 'framer-motion'
import { Target, BookOpen, MessageSquare, CheckCheck, MapPin, UtensilsCrossed, Loader2, Check, X } from 'lucide-react'
import type { PipelineStep } from '@/types/search'
import { cn } from '@/utils/cn'

const STEP_ICONS: Record<string, typeof Target> = {
  intent_parsing: Target,
  xhs_search: BookOpen,
  comment_analysis: MessageSquare,
  cross_validation: CheckCheck,
  poi_enrichment: MapPin,
  result_generation: UtensilsCrossed,
}

function StepIndicator({ step }: { step: PipelineStep }) {
  const Icon = STEP_ICONS[step.id] ?? Target

  if (step.status === 'loading') {
    return (
      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center">
        <Loader2 size={14} className="text-primary animate-spin" />
      </div>
    )
  }
  if (step.status === 'done') {
    return (
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        className="w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center"
      >
        <Check size={14} className="text-emerald-600" />
      </motion.div>
    )
  }
  if (step.status === 'error') {
    return (
      <div className="w-7 h-7 rounded-full bg-red-100 flex items-center justify-center">
        <X size={14} className="text-destructive" />
      </div>
    )
  }
  return (
    <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center">
      <Icon size={14} className="text-muted-foreground" />
    </div>
  )
}

export function SearchPipeline({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="space-y-0.5">
      {steps.map((step, i) => (
        <motion.div
          key={step.id}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className="flex items-center gap-3 py-1.5"
        >
          <div className="flex flex-col items-center">
            <StepIndicator step={step} />
            {i < steps.length - 1 && (
              <div className={cn('w-px h-3 mt-0.5', step.status === 'done' ? 'bg-emerald-200' : 'bg-border')} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className={cn(
              'text-xs leading-tight',
              step.status === 'loading' && 'text-primary font-medium',
              step.status === 'done' && 'text-foreground',
              step.status === 'error' && 'text-destructive',
              step.status === 'pending' && 'text-muted-foreground',
            )}>
              {step.label}
            </p>
            {step.detail && step.status !== 'pending' && (
              <p className="text-[10px] text-muted-foreground truncate mt-0.5">{step.detail}</p>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  )
}
