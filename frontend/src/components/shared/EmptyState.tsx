import { motion } from 'framer-motion'

interface EmptyStateProps {
  icon?: string
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ icon = '🍜', title, description, action }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-8 text-center"
    >
      <span className="text-6xl mb-4 block">{icon}</span>
      <h3 className="font-display text-lg font-semibold text-ink mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-muted max-w-[240px]">{description}</p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-5 px-5 py-2 bg-ember text-white text-sm font-medium rounded-full hover:bg-ember-light transition-colors"
        >
          {action.label}
        </button>
      )}
    </motion.div>
  )
}
