import type { QueryFamily } from '../../../shared/contracts'

export const evidenceObservabilityApi = {
  getQueryFamilies: async (): Promise<QueryFamily[]> => {
    return [
      {
        family_id: 'fam_hotpot_chengdu',
        pattern: '成都 * 市井火锅 * 本地',
        freshness_window_hours: 24,
        coverage_rate: 0.94,
        bundle_version: 'bundle_v2.4.1',
        watermark_updated_at: new Date(Date.now() - 1000 * 60 * 20).toISOString(),
        stale_objects_count: 2,
        active_objects_count: 46,
      },
      {
        family_id: 'fam_bistro_shanghai',
        pattern: '上海 * Bistro * 性价比',
        freshness_window_hours: 48,
        coverage_rate: 0.88,
        bundle_version: 'bundle_v1.9.0',
        watermark_updated_at: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
        stale_objects_count: 0,
        active_objects_count: 32,
      },
      {
        family_id: 'fam_morning_tea_guangzhou',
        pattern: '广州 * 早茶 * 老字号',
        freshness_window_hours: 72,
        coverage_rate: 0.96,
        bundle_version: 'bundle_v3.0.2',
        watermark_updated_at: new Date(Date.now() - 1000 * 60 * 180).toISOString(),
        stale_objects_count: 5,
        active_objects_count: 58,
      },
    ]
  },

  triggerRefresh: async (_familyId: string): Promise<{ success: boolean, newVersion: string }> => {
    await new Promise(r => setTimeout(r, 600))
    return {
      success: true,
      newVersion: `bundle_v${Math.floor(Math.random() * 5 + 1)}.${Math.floor(Math.random() * 9)}`,
    }
  },
}
