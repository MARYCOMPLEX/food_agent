import { describe, expect, it } from 'vitest'
import { platformAccountsApi } from '../features/platform-accounts/api/platformAccountsApi'
import { serviceCatalogApi } from '../features/service-catalog/api/serviceCatalogApi'
import { taskObservabilityApi } from '../features/task-observability/api/tasksApi'
import { evidenceObservabilityApi } from '../features/evidence-observability/api/evidenceApi'

describe('feature APIs and Observability Contracts', () => {
  it('manages local and remote platform accounts', async () => {
    const accounts = platformAccountsApi.getLocalAccounts()
    expect(Array.isArray(accounts)).toBe(true)
    expect(accounts.length).toBeGreaterThan(0)
    expect(accounts[0]?.platform).toBeTruthy()
  })

  it('fetches registered services from catalog', async () => {
    const services = await serviceCatalogApi.getServices()
    expect(Array.isArray(services)).toBe(true)
    expect(services.length).toBeGreaterThan(0)
    const xhsService = services.find(s => s.channels.includes('xhs_pc'))
    expect(xhsService).toBeDefined()
    expect(xhsService?.auth_ref).toContain('vault://')
  })

  it('filters observability tasks by type and status', async () => {
    const allTasks = await taskObservabilityApi.getTasks()
    expect(allTasks.length).toBeGreaterThan(0)

    const researchTasks = await taskObservabilityApi.getTasks({ type: 'research' })
    expect(researchTasks.every(t => t.type === 'research')).toBe(true)

    const completedTasks = await taskObservabilityApi.getTasks({ status: 'completed' })
    expect(completedTasks.every(t => t.status === 'completed')).toBe(true)
  })

  it('fetches query families and triggers evidence bundle refresh', async () => {
    const families = await evidenceObservabilityApi.getQueryFamilies()
    expect(families.length).toBeGreaterThan(0)
    const first = families[0]
    expect(first).toBeDefined()
    if (first) {
      expect(first.coverage_rate).toBeGreaterThan(0.5)
      const refreshResult = await evidenceObservabilityApi.triggerRefresh(first.family_id)
      expect(refreshResult.success).toBe(true)
      expect(refreshResult.newVersion).toMatch(/^bundle_v\d+\.\d+$/)
    }
  })
})
