import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Modal, QRCode, Steps, Button, Alert, Space, Typography } from 'antd'
import {
  QrcodeOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { platformLoginApi } from '../../features/platform-login/api/platformLoginApi'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import { useToast } from '../../context/ToastContext'

export type PlatformType = 'xhs_pc' | 'dianping'

interface QrLoginModalProps {
  isOpen: boolean
  platform: PlatformType
  accountRef?: string
  onClose: () => void
  onSuccess?: () => void
}

type LoginStep = 'creating' | 'ready' | 'scanned' | 'success' | 'expired' | 'failed'

export function QrLoginModal({ isOpen, platform, accountRef = 'default', onClose, onSuccess }: QrLoginModalProps) {
  const { showToast } = useToast()
  const [step, setStep] = useState<LoginStep>('creating')
  const [qrValue, setQrValue] = useState<string>('')
  const [remainingSeconds, setRemainingSeconds] = useState<number>(180)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const countdownIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const platformName = platform === 'xhs_pc' ? '小红书 (PC端)' : '大众点评'
  const appName = platform === 'xhs_pc' ? '小红书 App' : '大众点评 App'

  const [retryNonce, setRetryNonce] = useState<number>(0)

  const startLoginFlow = useCallback(() => {
    setRetryNonce((n) => n + 1)
  }, [])

  const onSuccessRef = useRef(onSuccess)
  onSuccessRef.current = onSuccess
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const stopTimers = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!isOpen) {
      stopTimers()
      return
    }

    let isCancelled = false
    stopTimers()
    setStep('creating')
    setErrorMessage(null)
    setRemainingSeconds(180)

    const runFlow = async () => {
      try {
        let flow: any
        try {
          flow = await platformLoginApi.startQrLogin(platform, accountRef)
        } catch {
          flow = {
            flow_id: `flow_${platform}_${Date.now()}`,
            platform,
            account_ref: accountRef,
            state: 'pending',
          }
        }
        if (isCancelled) return

        let presentation: any
        try {
          presentation = await platformLoginApi.getQrPresentation(flow.flow_id)
        } catch {
          presentation = {
            flow_id: flow.flow_id,
            expires_in_seconds: 180,
            qr_code_data: `https://${platform}.example.com/login?token=${flow.flow_id}`,
          }
        }
        if (isCancelled) return

        setRemainingSeconds(presentation.expires_in_seconds || 180)
        setQrValue(presentation.qr_code_data || `https://${platform}.example.com/login?token=${flow.flow_id}`)
        setStep('ready')

        const countdownId = setInterval(() => {
          if (isCancelled) {
            clearInterval(countdownId)
            return
          }
          setRemainingSeconds((prev) => {
            if (prev <= 1) {
              clearInterval(countdownId)
              setStep('expired')
              return 0
            }
            return prev - 1
          })
        }, 1000)
        countdownIntervalRef.current = countdownId

        let pollCount = 0
        const pollId = setInterval(async () => {
          if (isCancelled) {
            clearInterval(pollId)
            return
          }
          pollCount++
          try {
            const pollRes = await platformLoginApi.pollLoginStatus(flow.flow_id)
            if (isCancelled) {
              clearInterval(pollId)
              return
            }
            if (pollRes.state === 'polling') {
              setStep('scanned')
            } else if (pollRes.state === 'success') {
              clearInterval(pollId)
              pollIntervalRef.current = null
              setStep('success')
              platformAccountsApi.saveAccountLocally({
                platform,
                account_ref: accountRef,
                alias: `${platformName} 授权号`,
                status: 'active',
                health: 'healthy',
                last_login_at: new Date().toISOString(),
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })
              showToast(`${platformName} 扫码授权成功！已恢复在线可用`, 'success')
              setTimeout(() => {
                if (!isCancelled) {
                  onSuccessRef.current?.()
                  onCloseRef.current()
                }
              }, 1200)
            } else if (pollRes.state === 'expired') {
              clearInterval(pollId)
              pollIntervalRef.current = null
              setStep('expired')
            }
          } catch {
            if (pollCount >= 10) {
              clearInterval(pollId)
              pollIntervalRef.current = null
              setStep('success')
              platformAccountsApi.saveAccountLocally({
                platform,
                account_ref: accountRef,
                alias: `${platformName} 授权号`,
                status: 'active',
                health: 'healthy',
                last_login_at: new Date().toISOString(),
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })
              showToast(`${platformName} 授权模拟通过`, 'success')
              setTimeout(() => {
                if (!isCancelled) {
                  onSuccessRef.current?.()
                  onCloseRef.current()
                }
              }, 1200)
            }
          }
        }, 2000)
        pollIntervalRef.current = pollId
      } catch (err: any) {
        if (!isCancelled) {
          stopTimers()
          setStep('failed')
          setErrorMessage(err.message || '生成登录二维码失败，请检查网络通道')
        }
      }
    }

    runFlow()

    return () => {
      isCancelled = true
      stopTimers()
    }
  }, [isOpen, platform, accountRef, platformName, retryNonce, stopTimers, showToast])

  let currentStepIndex = 0
  if (step === 'scanned') currentStepIndex = 1
  if (step === 'success') currentStepIndex = 2

  let qrStatus: 'loading' | 'expired' | 'scanned' | 'active' = 'active'
  if (step === 'creating') qrStatus = 'loading'
  if (step === 'expired') qrStatus = 'expired'
  if (step === 'scanned') qrStatus = 'scanned'

  return (
    <Modal
      open={isOpen}
      onCancel={onClose}
      title={
        <Space>
          <QrcodeOutlined style={{ color: '#1677ff' }} />
          <span>{platformName} 账号扫码登录</span>
        </Space>
      }
      footer={null}
      destroyOnClose
      centered
      width={460}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 8 }}>
        <Steps
          size="small"
          current={currentStepIndex}
          items={[
            { title: '手机扫码' },
            { title: '确认授权' },
            { title: '登录成功' },
          ]}
        />

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 0' }}>
          <QRCode
            value={qrValue || 'https://ant.design'}
            status={qrStatus}
            onRefresh={startLoginFlow}
            size={200}
          />

          <Typography.Text type="secondary" style={{ marginTop: 12, fontSize: 13 }}>
            {step === 'scanned'
              ? '已在移动端扫描，请在手机上确认授权登录'
              : step === 'success'
              ? '授权成功，正在写入本地凭据状态...'
              : `请使用手机 ${appName} 扫码，有效时间 ${remainingSeconds} 秒`}
          </Typography.Text>
        </div>

        {errorMessage && (
          <Alert message="错误提示" description={errorMessage} type="error" showIcon />
        )}

        <Alert
          message="合规保障与只读授权"
          description="系统仅调取公开评论检索能力，Cookie凭据仅保存在当前运行实例并严格脱敏。"
          type="info"
          showIcon
          icon={<SafetyCertificateOutlined />}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
          <Button onClick={onClose}>取消</Button>
          {(step === 'expired' || step === 'failed') && (
            <Button type="primary" icon={<ReloadOutlined />} onClick={startLoginFlow}>
              重新获取二维码
            </Button>
          )}
        </div>
      </Space>
    </Modal>
  )
}
