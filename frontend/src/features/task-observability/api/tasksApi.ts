import type { ObservabilityTask } from '../../../shared/contracts'

export const taskObservabilityApi = {
  getTasks: async (params?: { type?: string, status?: string }): Promise<ObservabilityTask[]> => {
    // Generate realistic observability telemetry records
    const list: ObservabilityTask[] = [
      {
        task_id: 'task_res_9f82a1',
        session_id: 'session-cd78a1',
        type: 'research',
        status: 'completed',
        query: '成都市中心不用排队的市井老火锅',
        turn_count: 2,
        duration_ms: 1840,
        retry_count: 0,
        recovery_state: 'healthy',
        created_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
        updated_at: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
      },
      {
        task_id: 'task_ref_4b28c0',
        session_id: 'session-sh8830',
        type: 'refresh',
        status: 'completed',
        query: '上海静安寺周边高性价比Bistro',
        turn_count: 1,
        duration_ms: 920,
        retry_count: 0,
        recovery_state: 'healthy',
        created_at: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
        updated_at: new Date(Date.now() - 1000 * 60 * 44).toISOString(),
      },
      {
        task_id: 'task_med_11a8c9',
        session_id: 'session-gz9021',
        type: 'media',
        status: 'completed',
        query: '广州老字号早茶酒楼虾饺大比拼',
        turn_count: 1,
        duration_ms: 2400,
        retry_count: 1,
        recovery_state: 'recovered',
        created_at: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
        updated_at: new Date(Date.now() - 1000 * 60 * 88).toISOString(),
      },
      {
        task_id: 'task_res_3c90f2',
        session_id: 'session-cq7741',
        type: 'research',
        status: 'running',
        query: '重庆防空洞深处地道烤鱼',
        turn_count: 1,
        duration_ms: 650,
        retry_count: 0,
        recovery_state: 'healthy',
        created_at: new Date(Date.now() - 1000 * 30).toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]

    if (params?.type && params.type !== 'all') {
      return list.filter(t => t.type === params.type)
    }
    if (params?.status && params.status !== 'all') {
      return list.filter(t => t.status === params.status)
    }
    return list
  },
}
