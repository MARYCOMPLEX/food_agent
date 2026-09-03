export interface MustTryItem {
  name: string
  reason: string
  img: string
}

export interface BlackListItem {
  name: string
  reason: string
}

export interface ShopStats {
  flavor: string
  cost: string
  wait: string
  env: string
}

export interface WanghongAnalysis {
  score: 'definitely_wanghong' | 'likely_wanghong' | 'unknown' | 'likely_local' | 'definitely_local'
  confidence: number
  reasons: string[]
  indicators?: {
    has_queue_mentions: boolean
    has_photo_focus: boolean
    has_negative_service: boolean
    has_local_mentions: boolean
    has_years_mentioned: boolean
  }
}

export interface Restaurant {
  name: string
  location: string | null
  features: string[]
  source_notes: string[]
  confidence: number
  is_recommended: boolean
  filter_reason: string | null
  wanghong_analysis: WanghongAnalysis | null
  shopProfile: ShopProfile | null
  pros: string[]
  cons: string[]
  mustTry: MustTryItem[]
  blackList: BlackListItem[]
  stats: ShopStats
  tags: string[]
}

export interface ShopProfile {
  address?: string | null
  phone?: string | null
  rating?: number | string | null
  openingHours?: string | null
  imageUrl?: string | null
  images?: Array<string | { url?: string; image_url?: string; src?: string }>
  recommendedDishes?: string[]
  promotions?: unknown[]
  city?: string | null
  district?: string | null
  region?: string | null
  latitude?: number | null
  longitude?: number | null
  [key: string]: unknown
}
