import { useRef, useEffect, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

interface MobileSearchInputProps {
  onSubmit: (query: string) => void
  disabled?: boolean
  placeholder?: string
}

const MAX_HEIGHT = 160

export function MobileSearchInput({ onSubmit, disabled, placeholder }: MobileSearchInputProps) {
  const [value, setValue] = useState('')
  const [isFocused, setIsFocused] = useState(false)
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
    <div
      className={cn(
        'relative rounded-3xl border bg-card shadow-sm transition-all',
        isFocused
          ? 'border-brand/30 shadow-md ring-1 ring-brand/10'
          : 'border-border/80'
      )}
    >
      <div className="flex items-end gap-2 px-4 py-2.5">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          disabled={disabled}
          placeholder={placeholder ?? '问点什么...'}
          rows={1}
          className="min-h-[28px] max-h-[160px] flex-1 resize-none border-0 bg-transparent p-0 text-[15px] leading-7 shadow-none placeholder:text-muted-foreground/60 focus-visible:ring-0"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled && !hasText}
          aria-label="发送"
          className={cn(
            'shrink-0 size-8 rounded-full grid place-items-center transition-all duration-200 active:scale-90',
            hasText
              ? 'bg-brand text-white shadow-sm'
              : 'bg-secondary text-muted-foreground'
          )}
        >
          {disabled ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <ArrowUp className="size-4" strokeWidth={2.5} />
          )}
        </button>
      </div>
    </div>
  )
}
