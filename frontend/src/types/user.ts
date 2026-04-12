export interface UserProfile {
  id: string
  name: string
  email: string
  avatar: string
  location: string
  stats: {
    savedCount: number
    searchCount: number
  }
}

export interface HistoryItem {
  id: string
  query: string
  resultsCount: number
  location: string
  createdAt: string
  sessionId?: string
  status?: string
}
