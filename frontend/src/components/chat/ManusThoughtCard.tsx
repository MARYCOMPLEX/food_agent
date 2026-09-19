import React, { useState, useEffect, useRef } from 'react'
import { Typography, Tag, Button } from 'antd'
import {
  CheckCircleFilled,
  LoadingOutlined,
  DownOutlined,
  CompassOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

export interface PlanStep {
  id: string
  label: string
  status: 'idle' | 'running' | 'succeeded' | 'failed' | 'loading' | string
  detail?: string
}

export interface ManusThoughtCardProps {
  plan: PlanStep[]
  isRunning?: boolean
  statusMessage?: string
  className?: string
  style?: React.CSSProperties
}

export const ManusThoughtCard: React.FC<ManusThoughtCardProps> = ({
  plan,
  isRunning = false,
  statusMessage,
  className,
  style,
}) => {
  const [expanded, setExpanded] = useState<boolean>(true)
  const [seconds, setSeconds] = useState<number>(0)
  const timerRef = useRef<any>(null)

  // Track thinking / execution duration
  useEffect(() => {
    if (isRunning) {
      setExpanded(true)
      const start = Date.now()
      timerRef.current = setInterval(() => {
        setSeconds(Math.max(1, Math.floor((Date.now() - start) / 1000)))
      }, 1000)
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [isRunning])

  if (!plan || plan.length === 0) return null

  const runningStep = plan.find((s) => s.status === 'running' || s.status === 'loading')
  const completedSteps = plan.filter((s) => s.status === 'succeeded' || s.status === 'done').length
  const totalSteps = plan.length
  const allCompleted = completedSteps === totalSteps && !isRunning

  return (
    <div
      className={className}
      style={{
        border: isRunning ? '1px solid #bfdbfe' : '1px solid #e2e8f0',
        borderRadius: 14,
        background: isRunning
          ? 'linear-gradient(180deg, #f8faff 0%, #ffffff 100%)'
          : '#f8fafc',
        boxShadow: isRunning
          ? '0 2px 8px rgba(37, 99, 235, 0.06)'
          : '0 1px 2px rgba(0, 0, 0, 0.02)',
        overflow: 'hidden',
        transition: 'all 0.3s ease',
        ...style,
      }}
    >
      <style>{`
        @keyframes manusPulseRing {
          0% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.4);
          }
          70% {
            transform: scale(1);
            box-shadow: 0 0 0 6px rgba(37, 99, 235, 0);
          }
          100% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(37, 99, 235, 0);
          }
        }
        .manus-pulse-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background-color: #2563eb;
          display: inline-block;
          animation: manusPulseRing 1.8s infinite cubic-bezier(0.45, 0, 0.55, 1);
        }
      `}</style>

      {/* Header bar */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          userSelect: 'none',
          background: isRunning ? 'rgba(239, 246, 255, 0.5)' : 'transparent',
          borderBottom: expanded ? '1px solid #f1f5f9' : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          {isRunning ? (
            <span className="manus-pulse-dot" />
          ) : completedSteps > 0 ? (
            <CheckCircleFilled style={{ color: '#10b981', fontSize: 13 }} />
          ) : (
            <ClockCircleOutlined style={{ color: '#94a3b8', fontSize: 13 }} />
          )}

          <Typography.Text strong style={{ fontSize: 13, color: '#0f172a' }}>
            {isRunning
              ? 'Agent 深度探店与分析中'
              : completedSteps > 0
              ? '全网探店调研已完成'
              : '探店调研步骤'}
          </Typography.Text>

          {isRunning ? (
            <Tag
              bordered={false}
              style={{
                background: '#dbeafe',
                color: '#1d4ed8',
                borderRadius: 12,
                fontSize: 11,
                padding: '0 8px',
                margin: 0,
                maxWidth: 220,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {runningStep ? runningStep.label : '进行中...'}
            </Tag>
          ) : (
            <Tag
              bordered={false}
              style={{
                background: completedSteps > 0 ? '#ecfdf5' : '#f1f5f9',
                color: completedSteps > 0 ? '#047857' : '#64748b',
                borderRadius: 12,
                fontSize: 11,
                padding: '0 8px',
                margin: 0,
              }}
            >
              {allCompleted
                ? `全部 ${totalSteps} 阶段`
                : completedSteps > 0
                ? `已完成 ${completedSteps}/${totalSteps} 步`
                : `共 ${totalSteps} 步`}
            </Tag>
          )}

          {seconds > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 2 }}>
              {seconds}s
            </Typography.Text>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <Button
            type="text"
            size="small"
            style={{
              padding: '0 4px',
              height: 22,
              fontSize: 11,
              color: '#64748b',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <span>{expanded ? '收起' : '展开过程'}</span>
            <DownOutlined
              style={{
                fontSize: 9,
                transition: 'transform 0.2s',
                transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              }}
            />
          </Button>
        </div>
      </div>

      {/* Body / Step Flow */}
      {expanded && (
        <div style={{ padding: '12px 14px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {plan.map((step, idx) => {
              const isLast = idx === plan.length - 1
              const isStepRunning = isRunning && (step.status === 'running' || step.status === 'loading')
              const isStepSucceeded = step.status === 'succeeded' || step.status === 'done'

              return (
                <div key={step.id || idx} style={{ display: 'flex', gap: 10 }}>
                  {/* Timeline icon and vertical connector line */}
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      width: 16,
                      flexShrink: 0,
                    }}
                  >
                    <div style={{ height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {isStepSucceeded ? (
                        <CheckCircleFilled style={{ color: '#10b981', fontSize: 13 }} />
                      ) : isStepRunning ? (
                        <LoadingOutlined style={{ color: '#2563eb', fontSize: 12 }} />
                      ) : (
                        <span
                          style={{
                            width: 7,
                            height: 7,
                            borderRadius: '50%',
                            border: '1.5px solid #cbd5e1',
                            display: 'inline-block',
                          }}
                        />
                      )}
                    </div>
                    {!isLast && (
                      <div
                        style={{
                          width: 1.5,
                          flex: 1,
                          minHeight: 12,
                          background: isStepSucceeded ? '#a7f3d0' : '#e2e8f0',
                        }}
                      />
                    )}
                  </div>

                  {/* Step Content */}
                  <div
                    style={{
                      flex: 1,
                      minWidth: 0,
                      padding: isStepRunning ? '4px 10px 6px 10px' : '2px 0 6px 0',
                      borderRadius: isStepRunning ? 8 : 0,
                      background: isStepRunning ? '#eff6ff' : 'transparent',
                      border: isStepRunning ? '1px solid #dbeafe' : 'none',
                      marginBottom: isStepRunning ? 4 : 0,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <Typography.Text
                        strong={isStepRunning}
                        style={{
                          fontSize: 12,
                          color: isStepRunning ? '#1d4ed8' : isStepSucceeded ? '#334155' : '#94a3b8',
                        }}
                      >
                        {step.label}
                      </Typography.Text>
                      {isStepRunning && (
                        <span style={{ fontSize: 10, color: '#3b82f6', fontWeight: 500 }}>进行中...</span>
                      )}
                    </div>

                    {isStepRunning && (step.detail || statusMessage) && (
                      <div
                        style={{
                          marginTop: 3,
                          fontSize: 11,
                          color: '#2563eb',
                          fontFamily: 'SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 4,
                        }}
                      >
                        <span style={{ opacity: 0.7 }}>↳</span>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {step.detail || statusMessage}
                        </span>
                      </div>
                    )}

                    {isStepSucceeded && step.detail && step.detail !== step.label && (
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>
                        {step.detail}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Active Live Action Banner at bottom of Thought Card */}
          {isRunning && statusMessage && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px dashed #e2e8f0',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 11,
                color: '#0284c7',
              }}
            >
              <CompassOutlined style={{ fontSize: 12 }} />
              <Typography.Text
                style={{
                  fontSize: 11,
                  color: '#0369a1',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {statusMessage}
              </Typography.Text>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
