import React, { useState, useEffect } from 'react'
import {
  Shield,
  CheckCircle2,
  AlertTriangle,
  QrCode,
  RefreshCw,
  Info,
  Lock,
  ExternalLink,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { platformAccountsApi } from '../../features/platform-accounts/api/platformAccountsApi'
import { QrLoginModal } from '../../components/auth/QrLoginModal'
import { useToast } from '../../context/ToastContext'
import type { PlatformAccount } from '../../shared/contracts'

export function PlatformAccountsPage() {
  const { showToast } = useToast()
  const [accounts, setAccounts] = useState<PlatformAccount[]>([])
  const [loginModalPlatform, setLoginModalPlatform] = useState<'xhs_pc' | 'dianping' | null>(null)
  const [selectedAccountForLogin, setSelectedAccountForLogin] = useState<string>('default')

  const refreshAccounts = () => {
    setAccounts(platformAccountsApi.getLocalAccounts())
  }

  useEffect(() => {
    refreshAccounts()
  }, [])

  const handleOpenLogin = (platform: 'xhs_pc' | 'dianping', accountRef: string) => {
    setLoginModalPlatform(platform)
    setSelectedAccountForLogin(accountRef)
  }

  const handleToggleStatus = (account: PlatformAccount) => {
    const isNowExpired = account.status === 'active'
    platformAccountsApi.saveAccountLocally({
      ...account,
      status: isNowExpired ? 'expired' : 'active',
      health: isNowExpired ? 'warning' : 'healthy',
      updated_at: new Date().toISOString(),
    })
    refreshAccounts()
    showToast(
      isNowExpired
        ? `已将 ${account.alias} 标记为待重新验证状态（用于测试降级）`
        : `已将 ${account.alias} 恢复为有效状态`,
      'info',
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
          <Shield className="w-6 h-6 text-orange-600" />
          <span>平台数据源与账号连接</span>
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          管理用于深度调查的数据源账号。所有抓取均仅读取公开评论与门店档案，零明文凭据存储。
        </p>
      </div>

      {/* Security Banner */}
      <div className="p-4 rounded-2xl bg-slate-900 text-white flex items-start gap-3 shadow-sm">
        <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-semibold text-slate-100">高标准端内隐私与安全隔离</div>
          <div className="text-slate-300 leading-relaxed">
            系统绝不要求输入平台密码，不向客户端明文暴露 Cookie、Token 或 Secret。扫码授权成功后，凭据仅在沙箱容器中以加密哈希存储。
          </div>
        </div>
      </div>

      {/* Account Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Xiaohongshu Card */}
        {(() => {
          const acc = accounts.find((a) => a.platform === 'xhs_pc') || {
            platform: 'xhs_pc',
            account_ref: 'xhs_collector_01',
            alias: '小红书默认探索采集号',
            status: 'active',
            health: 'healthy',
          }
          const isActive = acc.status === 'active' && acc.health === 'healthy'

          return (
            <div className="bg-white rounded-2xl border border-slate-200/90 p-5 shadow-xs flex flex-col justify-between space-y-5">
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-10 h-10 rounded-xl bg-red-50 text-red-600 font-extrabold flex items-center justify-center text-sm border border-red-100">
                      RED
                    </div>
                    <div>
                      <h3 className="font-bold text-slate-900 text-base">小红书 (PC端)</h3>
                      <div className="text-xs text-slate-500">{acc.alias}</div>
                    </div>
                  </div>

                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                      isActive
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : 'bg-amber-50 text-amber-700 border-amber-200'
                    }`}
                  >
                    {isActive ? (
                      <>
                        <CheckCircle2 className="w-3 h-3" />
                        <span>已连接就绪</span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="w-3 h-3" />
                        <span>需重新登录</span>
                      </>
                    )}
                  </span>
                </div>

                {/* Capabilities */}
                <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100 space-y-2 text-xs">
                  <div className="font-semibold text-slate-700">核心承担职责：</div>
                  <ul className="space-y-1 text-slate-600 leading-relaxed">
                    <li className="flex items-center gap-1.5">
                      <span className="text-orange-500 font-bold">•</span>
                      <span>检索美食笔记与高赞/高频互动评论</span>
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="text-orange-500 font-bold">•</span>
                      <span>提炼真实到店体验反例、排队时长、口味分歧</span>
                    </li>
                  </ul>
                </div>

                {/* Impact if disconnected */}
                {!isActive && (
                  <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-start gap-1.5">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                    <span>失效影响：核心评论证据可能无法取得，调查将受阻或仅依赖已有缓存。</span>
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                <button
                  onClick={() => handleToggleStatus(acc)}
                  className="text-xs text-slate-400 hover:text-slate-600 underline"
                >
                  {isActive ? '模拟失效' : '模拟就绪'}
                </button>

                <button
                  onClick={() => handleOpenLogin('xhs_pc', acc.account_ref)}
                  className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-xs"
                >
                  <QrCode className="w-4 h-4" />
                  <span>{isActive ? '重新扫码登录' : '立即扫码登录'}</span>
                </button>
              </div>
            </div>
          )
        })()}

        {/* Dazhong Dianping Card */}
        {(() => {
          const acc = accounts.find((a) => a.platform === 'dianping') || {
            platform: 'dianping',
            account_ref: 'dp_crawler_main',
            alias: '大众点评主流口碑采集源',
            status: 'active',
            health: 'healthy',
          }
          const isActive = acc.status === 'active' && acc.health === 'healthy'

          return (
            <div className="bg-white rounded-2xl border border-slate-200/90 p-5 shadow-xs flex flex-col justify-between space-y-5">
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-10 h-10 rounded-xl bg-orange-50 text-orange-600 font-extrabold flex items-center justify-center text-sm border border-orange-100">
                      DP
                    </div>
                    <div>
                      <h3 className="font-bold text-slate-900 text-base">大众点评</h3>
                      <div className="text-xs text-slate-500">{acc.alias}</div>
                    </div>
                  </div>

                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                      isActive
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : 'bg-amber-50 text-amber-700 border-amber-200'
                    }`}
                  >
                    {isActive ? (
                      <>
                        <CheckCircle2 className="w-3 h-3" />
                        <span>已连接就绪</span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="w-3 h-3" />
                        <span>需重新验证</span>
                      </>
                    )}
                  </span>
                </div>

                {/* Capabilities */}
                <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100 space-y-2 text-xs">
                  <div className="font-semibold text-slate-700">核心承担职责：</div>
                  <ul className="space-y-1 text-slate-600 leading-relaxed">
                    <li className="flex items-center gap-1.5">
                      <span className="text-orange-500 font-bold">•</span>
                      <span>补充店铺精确地址、商圈、营业时间、联系电话</span>
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="text-orange-500 font-bold">•</span>
                      <span>提取招牌推荐菜品图片、人均价格与基础星级档案</span>
                    </li>
                  </ul>
                </div>

                {/* Impact if disconnected */}
                {!isActive && (
                  <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-start gap-1.5">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                    <span>失效影响：仍可调查评论，但到店地址、营业时间等店铺事实可能不完整。</span>
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                <button
                  onClick={() => handleToggleStatus(acc)}
                  className="text-xs text-slate-400 hover:text-slate-600 underline"
                >
                  {isActive ? '模拟失效' : '模拟就绪'}
                </button>

                <button
                  onClick={() => handleOpenLogin('dianping', acc.account_ref)}
                  className="px-4 py-2 rounded-xl bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-xs"
                >
                  <QrCode className="w-4 h-4" />
                  <span>{isActive ? '重新扫码登录' : '立即扫码登录'}</span>
                </button>
              </div>
            </div>
          )
        })()}
      </div>

      {/* QR Login Modal */}
      {loginModalPlatform && (
        <QrLoginModal
          isOpen={true}
          platform={loginModalPlatform}
          accountRef={selectedAccountForLogin}
          onClose={() => setLoginModalPlatform(null)}
          onSuccess={() => {
            refreshAccounts()
            setLoginModalPlatform(null)
          }}
        />
      )}
    </div>
  )
}
