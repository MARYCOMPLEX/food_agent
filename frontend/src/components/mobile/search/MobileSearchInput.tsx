import { useRef, useEffect, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Plus, Mic, Search, Sparkles, Image, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

interface MobileSearchInputProps {
  onSubmit: (query: string) => void
  disabled?: boolean
  placeholder?: string
}

interface Tool {
  icon: typeof Search
  label: string
}

const TOOLS: readonly Tool[] = [
  { icon: Search, label: '搜索' },
  { icon: Sparkles, label: '深度' },
  { icon: Image, label: '图片' },
] as const

const MAX_HEIGHT = 160

export function MobileSearchInput({ onSubmit, disabled, placeholder }: MobileSearchInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const handleSubmit = () => {
    const q = value.trim()
    if (!q || disabled) return
    onSubmit(q)
    setValue('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const hasText = value.trim().length > 0

  return (
    <div className="rounded-[28px] border border-border bg-bg-elev shadow-sm px-2.5 pt-2 pb-2 flex flex-col gap-1.5">
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder ?? '问点什么'}
        rows={1}
        className="min-h-[24px] max-h-[160px] resize-none border-0 bg-transparent shadow-none px-2 py-1.5 text-base leading-6 focus-visible:ring-0"
      />
      <div className="flex items-center gap-1.5 overflow-x-auto hide-scrollbar">
        <Button
          type="button"
          variant="outline"
          size="icon"
          disabled={disabled}
          aria-label="更多"
          className="shrink-0 size-9 rounded-full"
        >
          <Plus className="size-4" />
        </Button>
        {TOOLS.map(({ icon: Icon, label }) => (
          <Button
            key={label}
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            className="shrink-0 h-9 rounded-full px-3 text-xs gap-1.5"
          >
            <Icon className="size-3.5" />
            {label}
          </Button>
        ))}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled && !hasText}
          aria-label={hasText ? '发送' : '语音'}
          className={cn(
            'ml-auto shrink-0 size-9 rounded-full grid place-items-center transition-all active:scale-95',
            hasText ? 'bg-foreground text-background' : 'bg-muted-foreground/70 text-background'
          )}
        >
          {disabled ? (
            <Loader2 className="size-4 animate-spin" />
          ) : hasText ? (
            <ArrowUp className="size-4" strokeWidth={2.5} />
          ) : (
            <Mic className="size-4" />
          )}
        </button>
      </div>
    </div>
  )
}
