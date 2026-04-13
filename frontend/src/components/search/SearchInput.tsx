import { useState, useRef } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils/cn'

interface SearchInputProps {
  onSubmit: (query: string) => void
  disabled?: boolean
  placeholder?: string
}

export function SearchInput({ onSubmit, disabled, placeholder }: SearchInputProps) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = () => {
    const q = value.trim()
    if (!q || disabled) return
    onSubmit(q)
    setValue('')
  }

  return (
    <div className="sticky bottom-[72px] z-30 px-3 pb-3 pt-2 bg-gradient-to-t from-background via-background to-background/0">
      <div className={cn(
        'flex items-center gap-2 bg-card rounded-xl border px-3 py-2 shadow-lg transition-all',
        !disabled && 'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1',
      )}>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          disabled={disabled}
          placeholder={placeholder ?? '想吃什么？比如：杭州本地人爱去的面馆'}
          className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 outline-none disabled:opacity-50"
        />
        <Button
          size="icon"
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          className="shrink-0 h-8 w-8 rounded-lg"
        >
          {disabled ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
        </Button>
      </div>
    </div>
  )
}
