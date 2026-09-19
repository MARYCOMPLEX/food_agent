import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Modal, QRCode, Steps, Button, Alert, Space, Typography, Spin } from 'antd'
import {
  QrcodeOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { platformLoginApi } from '../../features/platform-login/api/platformLoginApi'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import { useToast } from '../../context/ToastContext'

export type PlatformType = 'xhs_pc' | 'dianping' | 'xiecheng' | string

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
  const [qrImageUrl, setQrImageUrl] = useState<string | null>(null)
  const [remainingSeconds, setRemainingSeconds] = useState<number>(180)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [imageLoaded, setImageLoaded] = useState<boolean>(false)
  const [imageRetryCount, setImageRetryCount] = useState<number>(0)

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const countdownIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const platformName =
    platform === 'xhs_pc' ? '小红书 (PC端)' :
    (platform === 'xiecheng' || platform === 'ctrip') ? '携程' :
    platform === 'dianping' ? '大众点评' : platform
  const appName =
    platform === 'xhs_pc' ? '小红书 App' :
    (platform === 'xiecheng' || platform === 'ctrip') ? '携程旅行 App' :
    platform === 'dianping' ? '大众点评 App' : `${platform} App`

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
    setImageLoaded(false)
    setImageRetryCount(0)

    const runFlow = async () => {
      try {
        setErrorMessage(null)
        setQrImageUrl(null)
        setQrValue('')
        setImageLoaded(false)
        setImageRetryCount(0)

        const flow = await platformLoginApi.startQrLogin(platform, accountRef)
        const flowId = (flow as any)?.flow_id || (flow as any)?.flow?.flow_id
        if (isCancelled || !flowId) return

        let presentation: any = null
        for (let attempt = 0; attempt < 10; attempt++) {
          if (isCancelled) return
          try {
            presentation = await platformLoginApi.getQrPresentation(flowId)
            if (presentation) break
          } catch (err: any) {
            if (attempt < 9) {
              await new Promise((r) => setTimeout(r, 1000))
            } else {
              throw err
            }
          }
        }
        if (isCancelled || !presentation) return

        setRemainingSeconds(presentation.expires_in_seconds || 180)

        if (presentation.image_url) {
          setQrImageUrl(presentation.image_url)
          setQrValue('')
        } else if (presentation.presentation_ref?.startsWith('/')) {
          setQrImageUrl(presentation.presentation_ref)
          setQrValue('')
        } else {
          const code = presentation.qr_code_data || presentation.qr_code_url || presentation.presentation_ref || ''
          setQrValue(code)
          setQrImageUrl(null)
        }
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
            const pollRes = await platformLoginApi.pollLoginStatus(flowId)
            if (isCancelled) {
              clearInterval(pollId)
              return
            }
            const rawState = (pollRes as any)?.state || (pollRes as any)?.status || (pollRes as any)?.data?.state || (pollRes as any)?.flow?.state || ''
            const flowState = String(rawState).toLowerCase()
            const isSuccess = ['success', 'succeeded', 'authenticated', 'logged_in', 'active'].includes(flowState) ||
                              Boolean((pollRes as any)?.logged_in) ||
                              Boolean((pollRes as any)?.data?.logged_in)

            if (isSuccess) {
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
            } else if (flowState === 'polling' || flowState === 'scanned' || flowState === 'waiting_for_confirmation') {
              setStep('scanned')
            } else if (flowState === 'expired') {
              clearInterval(pollId)
              pollIntervalRef.current = null
              setStep('expired')
            } else if (flowState === 'failed' || flowState === 'cancelled') {
              clearInterval(pollId)
              pollIntervalRef.current = null
              setStep('failed')
              setErrorMessage((pollRes as any)?.error_message || (pollRes as any)?.data?.error_message || '登录失败，请重试')
            }
          } catch {
            // Temporary network error during poll, continue polling
          }
        }, 2000)
        pollIntervalRef.current = pollId
      } catch (err: any) {
        if (!isCancelled) {
          stopTimers()
          setStep('failed')
          const msg = err?.response?.data?.message || err?.message || '生成登录二维码失败，请检查网络通道'
          setErrorMessage(msg)
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
          {qrImageUrl ? (
            <div
              style={{
                position: 'relative',
                width: 200,
                height: 200,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#fff',
                borderRadius: 8,
                border: '1px solid #f0f0f0',
                overflow: 'hidden',
              }}
            >
              {(!imageLoaded || qrStatus === 'loading') && (
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#fff', zIndex: 1, padding: 16, textAlign: 'center' }}>
                  {imageRetryCount >= 30 ? (
                    <>
                      <Typography.Text type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
                        二维码加载超时
                      </Typography.Text>
                      <Button size="small" icon={<ReloadOutlined />} onClick={startLoginFlow}>
                        点击重试
                      </Button>
                    </>
                  ) : (
                    <Space direction="vertical" align="center" size={12}>
                      <Spin size="default" />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        正在生成二维码，约需3~5秒...
                      </Typography.Text>
                    </Space>
                  )}
                </div>
              )}
              <img
                key={`${qrImageUrl}-${imageRetryCount}`}
                src={imageRetryCount > 0 ? `${qrImageUrl}?t=${imageRetryCount}` : qrImageUrl}
                alt="登录二维码"
                onLoad={() => setImageLoaded(true)}
                onError={() => {
                  setImageLoaded(false)
                  if (imageRetryCount < 30) {
                    setTimeout(() => setImageRetryCount((c) => c + 1), 1000)
                  }
                }}
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                  display: imageLoaded ? 'block' : 'none',
                }}
              />
              {qrStatus === 'expired' && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    zIndex: 2,
                    background: 'rgba(255,255,255,0.85)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Typography.Text type="secondary" style={{ marginBottom: 8 }}>
                    二维码已失效
                  </Typography.Text>
                  <Button size="small" icon={<ReloadOutlined />} onClick={startLoginFlow}>
                    点击刷新
                  </Button>
                </div>
              )}
              {qrStatus === 'scanned' && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    zIndex: 2,
                    background: 'rgba(255,255,255,0.85)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Typography.Text strong style={{ color: '#52c41a' }}>
                    已扫码，请在手机上确认
                  </Typography.Text>
                </div>
              )}
            </div>
          ) : (
            <QRCode
              value={qrValue || 'https://ant.design'}
              status={qrStatus}
              onRefresh={startLoginFlow}
              size={200}
            />
          )}

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
