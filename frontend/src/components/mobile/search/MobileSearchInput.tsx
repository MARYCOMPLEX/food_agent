import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import { ArrowUp, Plus, Mic, Search, Sparkles, Image, Loader2 } from 'lucide-react'
import { cn } from '@/utils/cn'

interface Props {
  onSubmit: (query: string) => void
  disabled?: boolean
  placeholder?: string
}

const TOOLS = [
  { icon: Search, label: '搜索' },
  { icon: Sparkles, label: '深度' },
  { icon: Image, label: '图片' },
] as const

export function MobileSearchInput({ onSubmit, disabled, placeholder }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
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
    <div className="bg-bg-elev border border-border rounded-[28px] px-2.5 pt-2 pb-2 flex flex-col gap-1">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder ?? '问点什么'}
        rows={1}
        className="w-full resize-none border-0 outline-none bg-transparent text-foreground placeholder:text-muted-foreground text-[16px] leading-6 px-2 py-1.5 min-h-[24px] max-h-[160px] disabled:opacity-50"
      />
      <div className="flex items-center gap-1.5 overflow-x-auto hide-scrollbar">
        <button
          type="button"
          disabled={disabled}
          className="shrink-0 w-9 h-9 rounded-full border border-border bg-background grid place-items-center text-foreground active:bg-bg-elev transition-colors disabled:opacity-40"
          aria-label="更多"
        >
          <Plus size={18} strokeWidth={2} />
        </button>
        {TOOLS.map(({ icon: Icon, label }) => (
          <button
            key={label}
            type="button"
            disabled={disabled}
            className="shrink-0 flex items-center gap-1.5 h-9 px-3 rounded-full border border-border bg-background text-foreground text-[13px] active:bg-bg-elev transition-colors disabled:opacity-40"
          >
            <Icon size={14} strokeWidth={2} />
            {label}
          </button>
        ))}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled && !hasText}
          className={cn(
            'ml-auto shrink-0 w-9 h-9 rounded-full grid place-items-center transition-all active:scale-95',
            hasText
              ? 'bg-foreground text-background'
              : 'bg-muted-foreground/70 text-background'
          )}
          aria-label={hasText ? '发送' : '语音'}
        >
          {disabled ? (
            <Loader2 size={16} className="animate-spin" />
          ) : hasText ? (
            <ArrowUp size={16} strokeWidth={2.5} />
          ) : (
            <Mic size={16} strokeWidth={2} />
          )}
        </button>
      </div>
    </div>
  )
}
