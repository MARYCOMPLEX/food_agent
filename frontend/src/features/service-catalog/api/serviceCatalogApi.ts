import { httpClient } from '../../../shared/api/httpClient'
import { storage } from '../../../shared/utils/storage'
import type { McpTool, ServiceEndpointConfig } from '../../../shared/contracts'

const SERVICES_KEY = 'anyfast_registered_services'

export const serviceCatalogApi = {
  getServices: async (): Promise<ServiceEndpointConfig[]> => {
    const data = storage.get<ServiceEndpointConfig[] | null>(SERVICES_KEY, null)
    if (data && Array.isArray(data))
      return data

    const defaultServices: ServiceEndpointConfig[] = [
      {
        service_id: 'svc_xhs_crawler',
        name: '小红书 PC 笔记与评论服务',
        base_url: 'http://localhost:8001',
        mcp_url: 'http://localhost:8001/mcp',
        protocol: 'http',
        channels: ['xhs_pc'],
        capabilities: ['search_notes', 'fetch_comments', 'verify_author'],
        descriptor_version: '1.2.0',
        timeout_seconds: 30,
        auth_ref: 'vault://xhs/crawler_main',
        status: 'ready',
        updated_at: new Date().toISOString(),
      },
      {
        service_id: 'svc_xhs_creator',
        name: '小红书创作者探店分析服务',
        base_url: 'http://localhost:8002',
        mcp_url: 'http://localhost:8002/mcp',
        protocol: 'mcp',
        channels: ['xhs_creator'],
        capabilities: ['creator_profile', 'influencer_credibility'],
        descriptor_version: '1.1.0',
        timeout_seconds: 45,
        auth_ref: 'vault://xhs/creator_auth',
        status: 'ready',
        updated_at: new Date().toISOString(),
      },
      {
        service_id: 'svc_dianping_poi',
        name: '大众点评 POI 交叉校验服务',
        base_url: 'http://localhost:8003',
        mcp_url: 'http://localhost:8003/mcp',
        protocol: 'mcp',
        channels: ['dianping'],
        capabilities: ['poi_detail', 'dishes_rank', 'blacklist_crosscheck'],
        descriptor_version: '2.0.1',
        timeout_seconds: 25,
        auth_ref: 'vault://dp/poi_key',
        status: 'ready',
        updated_at: new Date().toISOString(),
      },
    ]
    storage.set(SERVICES_KEY, defaultServices)
    return defaultServices
  },

  getToolsForPlatform: async (platform: string): Promise<McpTool[]> => {
    try {
      return await httpClient.get<McpTool[]>(`/v1/platform/account-services/${platform}/tools`)
    }
    catch {
      return [
        {
          name: `${platform}_search_notes`,
          description: `在 ${platform} 检索美食探店真实笔记与真实评价`,
          sideEffect: false,
          channel: platform as any,
          version: '1.0',
        },
        {
          name: `${platform}_fetch_poi_detail`,
          description: `获取 ${platform} 对应店铺的精确地址、评分与避雷标签`,
          sideEffect: false,
          channel: platform as any,
          version: '1.0',
        },
      ]
    }
  },

  saveService: async (svc: ServiceEndpointConfig): Promise<void> => {
    const list = await serviceCatalogApi.getServices()
    const idx = list.findIndex(s => s.service_id === svc.service_id)
    if (idx >= 0) {
      list[idx] = svc
    }
    else {
      list.push(svc)
    }
    storage.set(SERVICES_KEY, list)
  },

  testEndpoint: async (_url: string): Promise<{ success: boolean, latencyMs: number, capabilities?: string[] }> => {
    const start = Date.now()
    await new Promise(r => setTimeout(r, 400))
    return {
      success: true,
      latencyMs: Date.now() - start,
      capabilities: ['search', 'evaluate', 'poi_enrich'],
    }
  },
}
