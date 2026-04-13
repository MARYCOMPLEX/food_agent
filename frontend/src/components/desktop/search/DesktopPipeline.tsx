import { Steps } from 'antd'
import type { PipelineStep } from '@/types/search'

const STATUS_MAP: Record<PipelineStep['status'], 'wait' | 'process' | 'finish' | 'error'> = {
  pending: 'wait',
  loading: 'process',
  done: 'finish',
  error: 'error',
}

interface Props {
  steps: PipelineStep[]
}

export function DesktopPipeline({ steps }: Props) {
  const currentIndex = steps.findIndex(
    (s) => s.status === 'loading' || s.status === 'error',
  )

  return (
    <Steps
      direction="vertical"
      size="small"
      current={currentIndex === -1 ? steps.length : currentIndex}
      items={steps.map((step) => ({
        title: step.label,
        description: step.detail || undefined,
        status: STATUS_MAP[step.status],
      }))}
    />
  )
}
