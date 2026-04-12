import { useState, useRef, useEffect } from 'react'
import { cn } from '../../utils/cn'

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

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
        const active = document.activeElement
        if (active?.tagName !== 'INPUT' && active?.tagName !== 'TEXTAREA') {
          e.preventDefault()
          inputRef.current?.focus()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="sticky bottom-16 z-30 px-3 pb-3 pt-2 bg-gradient-to-t from-cream via-cream to-cream/0">
      <div className={cn(
        'flex items-center gap-2 bg-white rounded-2xl border shadow-lg px-4 py-2.5 transition-all',
        disabled ? 'border-stone-200 opacity-70' : 'border-border hover:border-ember/30 focus-within:border-ember focus-within:shadow-ember/10'
      )}>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          disabled={disabled}
          placeholder={placeholder || '想吃什么？比如：杭州本地人爱去的面馆'}
          className="flex-1 bg-transparent text-sm text-ink placeholder:text-muted/60 outline-none"
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          className={cn(
            'shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all text-white text-sm',
            value.trim() && !disabled
              ? 'bg-ember hover:bg-ember-light active:scale-95'
              : 'bg-stone-200 cursor-not-allowed'
          )}
        >
          {disabled ? (
            <span className="w-4 h-4 border-2 border-white/60 border-t-transparent rounded-full animate-spin" />
          ) : (
            '↑'
          )}
        </button>
      </div>
    </div>
  )
}
