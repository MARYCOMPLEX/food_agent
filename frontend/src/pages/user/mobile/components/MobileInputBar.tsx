import React, { useRef } from 'react'
import { Input, Button, Tag, Space } from 'antd'
import {
  SendOutlined,
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
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          backgroundColor: '#f8f9fa',
          borderRadius: 20,
          border: '1px solid #e8e8e8',
          padding: '6px 10px',
        }}
      >
        <Input.TextArea
          ref={textareaRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
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
            padding: 0,
            fontSize: 14,
            lineHeight: 1.4,
            resize: 'none',
            flex: 1,
            backgroundColor: 'transparent',
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
            icon={<SendOutlined style={{ fontSize: 13 }} />}
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
            }}
          />
        )}
      </div>
    </div>
  )
}
