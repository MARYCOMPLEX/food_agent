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
  poi_details: {
    address?: string
    tel?: string
    rating?: string
    opentime?: string
    location?: string
    photos?: string[]
  } | null
  pros: string[]
  cons: string[]
  mustTry: MustTryItem[]
  blackList: BlackListItem[]
  stats: ShopStats
  tags: string[]
}
