import { httpClient } from '../../../shared/api/httpClient'
import type {
  FaqItem,
  FeedbackRequest,
  UserProfile,
} from '../../../shared/contracts'

export const profileApi = {
  getProfile: async (): Promise<UserProfile> => {
    return httpClient.get<UserProfile>('/v1/user/profile')
  },

  updateProfile: async (payload: { name?: string, email?: string, location?: string }): Promise<UserProfile> => {
    return httpClient.put<UserProfile>('/v1/user/profile', payload)
  },

  getSettings: async (): Promise<any> => {
    return httpClient.get<any>('/v1/user/settings')
  },

  updatePreferences: async (prefs: Record<string, any>): Promise<any> => {
    return httpClient.put<any>('/v1/user/preferences', prefs)
  },

  updateNotifications: async (notifs: Record<string, any>): Promise<any> => {
    return httpClient.put<any>('/v1/user/notifications', notifs)
  },

  getStats: async (type: 'saved' | 'reviews' | 'visited'): Promise<{ type: string, items: any[], total: number }> => {
    return httpClient.get<{ type: string, items: any[], total: number }>(`/v1/user/stats/${type}`)
  },

  getFaqs: async (): Promise<FaqItem[]> => {
    return httpClient.get<FaqItem[]>('/v1/help/faqs')
  },

  submitFeedback: async (feedback: FeedbackRequest): Promise<{ success: boolean, message: string }> => {
    return httpClient.post<{ success: boolean, message: string }>('/v1/help/feedback', feedback)
  },
}
