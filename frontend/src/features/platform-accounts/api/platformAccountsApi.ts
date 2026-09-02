import { httpClient } from '../../../shared/api/httpClient'
import { storage } from '../../../shared/utils/storage'
import type {
  PlatformAccount,
  PlatformAccountCreateRequest,
} from '../../../shared/contracts'

const ACCOUNTS_STORAGE_KEY = 'anyfast_saved_platform_accounts'

export const platformAccountsApi = {
  registerAccount: async (req: PlatformAccountCreateRequest): Promise<PlatformAccount> => {
    const acc = await httpClient.post<PlatformAccount>('/v1/platform/accounts', req)
    platformAccountsApi.saveAccountLocally(acc)
    return acc
  },

  getAccount: async (platform: string, accountRef: string): Promise<PlatformAccount> => {
    const acc = await httpClient.get<PlatformAccount>(`/v1/platform/accounts/${platform}/${accountRef}`)
    platformAccountsApi.saveAccountLocally(acc)
    return acc
  },

  getLocalAccounts: (): PlatformAccount[] => {
    const data = storage.get<PlatformAccount[] | null>(ACCOUNTS_STORAGE_KEY, null)
    if (data && Array.isArray(data))
      return data

    const defaultList: PlatformAccount[] = [
      {
        platform: 'xhs_pc',
        account_ref: 'xhs_collector_01',
        alias: '小红书默认探索采集号',
        status: 'active',
        health: 'healthy',
        session_version: 1,
        created_at: new Date().toISOString(),
      },
      {
        platform: 'dianping',
        account_ref: 'dp_crawler_main',
        alias: '大众点评主流口碑采集源',
        status: 'active',
        health: 'healthy',
        session_version: 1,
        created_at: new Date().toISOString(),
      },
    ]
    storage.set(ACCOUNTS_STORAGE_KEY, defaultList)
    return defaultList
  },

  saveAccountLocally: (acc: PlatformAccount) => {
    const current = platformAccountsApi.getLocalAccounts()
    const idx = current.findIndex(
      a => a.platform === acc.platform && a.account_ref === acc.account_ref,
    )
    if (idx >= 0) {
      current[idx] = { ...current[idx], ...acc }
    }
    else {
      current.push(acc)
    }
    storage.set(ACCOUNTS_STORAGE_KEY, current)
  },
}
