import { apiGet, apiPut, apiPost } from './client'

export async function getUserProfile() {
  return apiGet<{ success: boolean; data: unknown }>('/v1/user/profile')
}

export async function updateProfile(data: { name?: string; email?: string; location?: string }) {
  return apiPut<{ success: boolean }>('/v1/user/profile', data)
}

export async function submitFeedback(type: string, content: string, contact?: string) {
  return apiPost<{ success: boolean }>('/v1/help/feedback', { type, content, contact })
}

export async function getFaqs() {
  return apiGet<{ success: boolean; data: { faqs: unknown[] } }>('/v1/help/faqs')
}
