import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Server,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  ExternalLink,
  Shield,
  Layers,
} from 'lucide-react'
import { useToast } from '../../context/ToastContext'

interface ServiceRecord {
  serviceId: string
  name: string
  platform: string
  protocol: 'mcp' | 'http' | 'sse'
  discoveredTools: number
  allowedTools: number
  accountCount: number
  status: 'ready' | 'degraded' | 'unavailable'
  p95Latency: number
  lastRefreshed: string
}

export function ServiceCatalogPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [testingId, setTestingId] = useState<string | null>(null)

  const [services, setServices] = useState<ServiceRecord[]>([
    {
      serviceId: 'service_xhs_comment_collector',
      name: '小红书评论与笔记深度采集适配器',
      platform: 'xhs_pc',
      protocol: 'mcp',
      discoveredTools: 6,
      allowedTools: 6,
      accountCount: 2,
      status: 'ready',
      p95Latency: 380,
      lastRefreshed: '2026-09-11 01:10:00',
    },
    {
      serviceId: 'service_dianping_poi_enricher',
      name: '大众点评店铺与菜品事实补充服务',
      platform: 'dianping',
      protocol: 'mcp',
      discoveredTools: 5,
      allowedTools: 4,
      accountCount: 2,
      status: 'degraded',
      p95Latency: 640,
      lastRefreshed: '2026-09-11 01:05:00',
    },
    {
      serviceId: 'service_geo_router',
      name: '商圈与地理编码辅助路由',
      platform: 'system',
      protocol: 'http',
      discoveredTools: 3,
      allowedTools: 2,
      accountCount: 1,
      status: 'ready',
      p95Latency: 120,
      lastRefreshed: '2026-09-11 00:30:00',
    },
  ])

  const handleTestConnection = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setTestingId(id)
    setTimeout(() => {
      setTestingId(null)
      showToast('通道连通性测试通过，Ping 延迟正常', 'success')
    }, 900)
  }

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Server className="w-5 h-5 text-orange-500" />
            <span>服务与 MCP 工具目录</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            配置与观测上游数据源服务、MCP 工具暴露清单及管理层放行规则
          </p>
        </div>
      </div>

      {/* Services List */}
      <div className="grid grid-cols-1 gap-4">
        {services.map((svc) => {
          const isReady = svc.status === 'ready'
          const isTesting = testingId === svc.serviceId

          return (
            <div
              key={svc.serviceId}
              onClick={() => navigate(`/ops/services/${svc.serviceId}`)}
              className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl shadow-xs hover:border-slate-700 transition-all cursor-pointer group flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div className="space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-white text-base group-hover:text-orange-400 transition-colors">
                    {svc.name}
                  </h3>
                  <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-300 font-mono text-[11px]">
                    {svc.serviceId}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                      isReady
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                    }`}
                  >
                    {isReady ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                    <span>{isReady ? 'READY' : 'DEGRADED'}</span>
                  </span>
                </div>

                <div className="flex items-center gap-4 text-xs text-slate-400 font-mono flex-wrap">
                  <span>协议: {svc.protocol.toUpperCase()}</span>
                  <span>·</span>
                  <span>
                    工具目录: {svc.allowedTools} / {svc.discoveredTools} 放行
                  </span>
                  <span>·</span>
                  <span>可用账号: {svc.accountCount} 个</span>
                  <span>·</span>
                  <span>P95 延迟: {svc.p95Latency}ms</span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 flex-shrink-0 self-end md:self-center">
                <button
                  disabled={isTesting}
                  onClick={(e) => handleTestConnection(svc.serviceId, e)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
                >
                  <RefreshCw className={`w-3 h-3 ${isTesting ? 'animate-spin text-orange-400' : ''}`} />
                  <span>{isTesting ? '探测中...' : '测试连通性'}</span>
                </button>

                <div className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-orange-600 group-hover:bg-orange-500 text-white text-xs font-medium transition-colors shadow-xs">
                  <span>工具详情</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
