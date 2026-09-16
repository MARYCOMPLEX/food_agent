import React, { useRef, useState } from 'react'
import { Input, Button, Tag, Space } from 'antd'
import {
  ArrowUpOutlined,
  StopOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import type { AttachedContext } from '../../types'

interface MobileInputBarProps {
  inputText: string
  setInputText: (text: string) => void
  isRunning: boolean
  attachedContext: AttachedContext
  setAttachedContext: (ctx: AttachedContext) => void
  onSendMessage: (text?: string) => void
  onStop: () => void
  suggestions: string[]
  textareaRef: React.RefObject<any>
}

export function MobileInputBar({
  inputText,
  setInputText,
  isRunning,
  attachedContext,
  setAttachedContext,
  onSendMessage,
  onStop,
  suggestions,
  textareaRef,
}: MobileInputBarProps) {
  const isComposingRef = useRef(false)
  const [isFocused, setIsFocused] = useState(false)

  const isMultiline = inputText.includes('\n') || inputText.length > 28

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposingRef.current) {
      e.preventDefault()
      if (inputText.trim() && !isRunning) {
        onSendMessage()
      }
    }
  }

  return (
    <div
      style={{
        backgroundColor: '#fff',
        borderTop: '1px solid #f0f0f0',
        padding: '8px 12px calc(8px + env(safe-area-inset-bottom, 8px))',
        position: 'sticky',
        bottom: 0,
        zIndex: 40,
        flexShrink: 0,
        boxShadow: '0 -2px 10px rgba(0,0,0,0.03)',
      }}
    >
      <style>{`
        .mobile-input-capsule .ant-input,
        .mobile-input-capsule .ant-input:focus,
        .mobile-input-capsule textarea,
        .mobile-input-capsule textarea:focus,
        .mobile-input-capsule textarea:focus-visible {
          outline: none !important;
          box-shadow: none !important;
          border: none !important;
          background: transparent !important;
        }
      `}</style>

      {/* 1. Quick Suggestions (Horizontal scroll row) */}
      {!isRunning && suggestions.length > 0 && (
        <div
          style={{
            display: 'flex',
            overflowX: 'auto',
            gap: 6,
            paddingBottom: 6,
            scrollbarWidth: 'none',
          }}
        >
          {suggestions.map((sug, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => onSendMessage(sug)}
              style={{
                whiteSpace: 'nowrap',
                fontSize: 12,
                padding: '4px 10px',
                borderRadius: 12,
                backgroundColor: '#f5f5f5',
                border: '1px solid #e8e8e8',
                color: '#595959',
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              {sug}
            </button>
          ))}
        </div>
      )}

      {/* 2. Attached Context Tag */}
      {attachedContext && (
        <div style={{ marginBottom: 6 }}>
          <Tag
            closable
            color="processing"
            closeIcon={<CloseCircleOutlined />}
            onClose={() => setAttachedContext(null)}
            style={{ borderRadius: 10, fontSize: 12, padding: '2px 8px' }}
          >
            针对商户: {attachedContext.title}
          </Tag>
        </div>
      )}

      {/* 3. Input Box Row */}
      <div
        className="mobile-input-capsule"
        style={{
          display: 'flex',
          alignItems: isMultiline ? 'flex-end' : 'center',
          gap: 8,
          backgroundColor: isFocused ? '#fff' : '#f8f9fa',
          borderRadius: 22,
          border: isFocused ? '1.5px solid #1677ff' : '1px solid #e8e8e8',
          boxShadow: isFocused ? '0 0 0 3px rgba(22, 119, 255, 0.1)' : 'none',
          padding: '5px 8px 5px 12px',
          transition: 'border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease',
        }}
      >
        <Input.TextArea
          ref={textareaRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onCompositionStart={() => {
            isComposingRef.current = true
          }}
          onCompositionEnd={() => {
            isComposingRef.current = false
          }}
          placeholder={
            attachedContext
              ? `追问关于“${attachedContext.title}”的细节...`
              : '向 Food Agent 提问美食、避坑或排队...'
          }
          autoSize={{ minRows: 1, maxRows: 4 }}
          variant="borderless"
          disabled={isRunning}
          style={{
            padding: '2px 0',
            fontSize: 14,
            lineHeight: '22px',
            resize: 'none',
            flex: 1,
            backgroundColor: 'transparent',
            border: 'none',
            outline: 'none',
            boxShadow: 'none',
          }}
        />

        {isRunning ? (
          <Button
            type="primary"
            danger
            shape="circle"
            size="small"
            icon={<StopOutlined style={{ fontSize: 13 }} />}
            onClick={onStop}
            style={{
              flexShrink: 0,
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          />
        ) : (
          <Button
            type="primary"
            shape="circle"
            size="small"
            icon={<ArrowUpOutlined style={{ fontSize: 15 }} />}
            disabled={!inputText.trim()}
            onClick={() => onSendMessage()}
            style={{
              flexShrink: 0,
              width: 32,
              height: 32,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: inputText.trim() ? '#1677ff' : '#d9d9d9',
              borderColor: inputText.trim() ? '#1677ff' : '#d9d9d9',
              color: '#fff',
            }}
          />
        )}
      </div>
    </div>
  )
}
