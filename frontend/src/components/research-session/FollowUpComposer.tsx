import React, { useState, useRef, useEffect } from 'react'
import {
  Send,
  StopCircle,
  X,
  Sparkles,
  Tag,
  ArrowRight,
  HelpCircle,
} from 'lucide-react'

interface FollowUpComposerProps {
  isRunning: boolean
  attachedContext?: {
    type: 'shop' | 'controversy' | 'evidence' | 'general'
    title: string
    id?: string
  } | null
  onClearContext?: () => void
  onSendFollowUp: (query: string, context?: any) => Promise<void>
  onStop: () => void
  suggestions?: string[]
}

export function FollowUpComposer({
  isRunning,
  attachedContext,
  onClearContext,
  onSendFollowUp,
  onStop,
  suggestions = [],
}: FollowUpComposerProps) {
  const [inputText, setInputText] = useState<string>('')
  const [isComposing, setIsComposing] = useState<boolean>(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
    }
  }, [inputText])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSend = async () => {
    const text = inputText.trim()
    if (!text || isRunning) return

    try {
      await onSendFollowUp(text, attachedContext)
      setInputText('')
      onClearContext?.()
    } catch {
      // Keep input text on failure
    }
  }

  return (
    <div className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-lg p-3 space-y-2.5 transition-all">
      {/* Attached Context Chip (if any) */}
      {attachedContext && (
        <div className="flex items-center justify-between bg-orange-50/80 border border-orange-200/70 px-3 py-1.5 rounded-xl text-xs text-orange-950">
          <div className="flex items-center gap-1.5 truncate">
            <Tag className="w-3.5 h-3.5 text-orange-600 flex-shrink-0" />
            <span className="font-medium text-orange-700">
              {attachedContext.type === 'shop'
                ? '针对店铺'
                : attachedContext.type === 'controversy'
                ? '针对争议'
                : '携带上下文'}
              :
            </span>
            <span className="font-semibold truncate">{attachedContext.title}</span>
          </div>
          {onClearContext && (
            <button
              onClick={onClearContext}
              className="p-1 hover:bg-orange-100 rounded text-orange-600 ml-2"
              title="清除附加上下文"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Suggestion Chips */}
      {suggestions.length > 0 && !isRunning && (
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs no-scrollbar">
          <span className="text-slate-400 text-[11px] flex-shrink-0 flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-orange-500" />
            快捷追问：
          </span>
          {suggestions.slice(0, 4).map((sug, idx) => (
            <button
              key={idx}
              onClick={() => {
                setInputText(sug)
                textareaRef.current?.focus()
              }}
              className="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 flex-shrink-0 transition-colors whitespace-nowrap"
            >
              {sug}
            </button>
          ))}
        </div>
      )}

      {/* Input Form */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          rows={1}
          placeholder={
            attachedContext
              ? `就“${attachedContext.title}”提出具体问题，例如：排队严重吗？锅底咸不咸？`
              : '继续追问或调整条件，例如：“步行20分钟内”、“有无免辣选择”、“只看前两家”...'
          }
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onKeyDown={handleKeyDown}
          disabled={isRunning}
          className="flex-1 resize-none bg-slate-50 border border-slate-200 focus:bg-white focus:border-orange-500 focus:ring-2 focus:ring-orange-100 rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-slate-900 placeholder-slate-400 focus:outline-none transition-all max-h-32 disabled:bg-slate-100 disabled:text-slate-400"
        />

        {isRunning ? (
          <button
            onClick={onStop}
            className="p-2.5 rounded-xl bg-rose-50 text-rose-600 hover:bg-rose-100 border border-rose-200 flex-shrink-0 transition-colors shadow-xs"
            title="停止当前调查"
          >
            <StopCircle className="w-5 h-5" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!inputText.trim()}
            className="p-2.5 rounded-xl bg-slate-900 hover:bg-orange-600 text-white flex-shrink-0 transition-colors disabled:opacity-30 disabled:hover:bg-slate-900 shadow-sm"
            title="发送追问"
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  )
}
