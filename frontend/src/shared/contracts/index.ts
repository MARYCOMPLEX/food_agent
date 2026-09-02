/**
 * Shared API & Domain Contracts for AnyFast / Food Agent.
 * Aligned with openapi.yaml and backend Python schemas.
 */

export type PlatformChannel = 'xhs_pc' | 'xhs_creator' | 'dianping'
export type AccountStatus = 'active' | 'degraded' | 'expired' | 'disabled'
export type AccountHealth = 'healthy' | 'warning' | 'critical' | 'unknown'
export type LoginMode = 'qr' | 'manual'
export type FlowState = 'pending' | 'polling' | 'success' | 'expired' | 'risk' | 'failed' | 'cancelled'
export type ReadinessState = 'ready' | 'degraded' | 'dependency-unavailable' | 'disabled'
export type SearchActionType = 'new_search' | 'refine' | 'recover'
export type ResearchStepId = 'intent_parser' | 'search' | 'analyzer' | 'poi_enricher' | 'verifier'
export type StepStatus = 'pending' | 'loading' | 'done' | 'error'
export type UserStatType = 'saved' | 'reviews' | 'visited'

export interface MustTryItem {
  name: string
  reason?: string | null
  img?: string | null
}

export interface BlackListItem {
  name: string
  reason?: string | null
}

export interface RestaurantStats {
  flavor?: string
  cost?: string
  wait?: string
  env?: string
}

export interface Restaurant {
  id: string
  name: string
  chnName?: string | null
  distance?: string | null
  price?: string
  trustScore?: number
  oneLiner?: string
  isNegativeOneLiner?: boolean
  tags?: string[]
  coverImage?: string | null
  pros?: string[]
  cons?: string[]
  warning?: string | null
  mustTry?: MustTryItem[]
  blackList?: BlackListItem[]
  stats?: RestaurantStats | null
  address?: string | null
  phone?: string | null
  hours?: string | null
  rating?: number | null
  authenticity?: string | null
  confidence?: number | null
  sourceNotesCount?: number | null
  sourceCommentsCount?: number | null
  updatedAt?: string | null
}

export interface UnifiedSearchRequest {
  query?: string
  sessionId?: string
  location?: { lat: number, lng: number } | null
  city?: string
  budget?: string
  taste?: string
  source?: PlatformChannel | 'all'
  mode?: 'reuse' | 'incremental' | 'new'
}

export interface SearchAdmission {
  sessionId: string
  streamUrl?: string
  taskId?: string
  turnId?: number
  action: SearchActionType
}

export interface LoadingStep {
  id: string
  label: string
  status: StepStatus
  detail?: string
}

export interface SearchStatusSnapshot {
  sessionId: string
  status: string
  currentStep?: string
  progress?: number
  steps?: LoadingStep[]
  error?: string | null
}

export interface SearchResultsSnapshot {
  sessionId: string
  status: string
  recommendations: Restaurant[]
  summary?: string
  turnId?: number
  filteredCount?: number
  clarifyQuestions?: string[]
}

export interface StreamEvent {
  event: 'status' | 'progress' | 'result' | 'error' | 'done'
  data: Record<string, any>
  id?: string
}

export interface FavoriteAddRequest {
  restaurantId: string
}

export interface FavoriteResponse {
  success: boolean
  message: string
  isFavorite: boolean
}

export interface FavoriteItem {
  id?: string
  restaurant_id: string
  restaurant?: Restaurant
  user_id?: string
  created_at?: string
  is_expired?: boolean
}

export interface HistoryItem {
  id: string | number
  query: string
  results_count?: number
  location?: string | null
  created_at?: string
  session_id?: string | null
}

export interface HistoryAddRequest {
  query: string
  resultsCount: number
  location?: string | null
}

export interface PlatformAccount {
  tenant_id?: string | null
  service_id?: string | null
  platform: PlatformChannel | string
  account_ref: string
  alias: string
  status: AccountStatus | string
  health: AccountHealth | string
  session_version?: number | null
  provider_subject_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  last_login_at?: string | null
}

export interface PlatformAccountCreateRequest {
  platform: string
  account_ref: string
  alias: string
  permissions?: string[] | null
}

export interface PlatformLoginFlow {
  flow_id: string
  service_id?: string | null
  platform: PlatformChannel | string
  account_ref?: string | null
  state: FlowState | string
  created_at?: string
  expires_at?: string
  updated_at?: string
  qr_expires_at?: string | null
  provider_subject_id?: string | null
  error_code?: string | null
  error_message?: string | null
}

export interface PlatformQrPresentation {
  flow_id: string
  qr_code_url?: string
  qr_code_data?: string
  expires_in_seconds?: number
  status: string
}

export interface PlatformReadinessResponse {
  state: ReadinessState | string
  ready: boolean
  login?: {
    enabled: boolean
  }
  login_runtime?: {
    enabled: boolean
    execution?: string
  }
  account_services?: {
    enabled: boolean
    ready: boolean
    state: string
  }
  dependencies?: Record<string, {
    status: ReadinessState | string
    message?: string
    latency_ms?: number
  }>
  recent_errors?: Array<{
    timestamp: string
    source: string
    code: string
    message: string
  }>
}

export interface McpToolSchema {
  type: string
  properties?: Record<string, any>
  required?: string[]
}

export interface McpTool {
  name: string
  description?: string
  inputSchema?: McpToolSchema
  sideEffect?: boolean
  channel?: PlatformChannel
  version?: string
}

export interface ServiceEndpointConfig {
  service_id: string
  name: string
  base_url: string
  mcp_url?: string
  protocol: 'http' | 'mcp' | 'sse'
  channels: PlatformChannel[]
  capabilities: string[]
  descriptor_version: string
  timeout_seconds: number
  auth_ref?: string
  status: ReadinessState
  created_at?: string
  updated_at?: string
}

export interface UserPreferences {
  theme?: 'light' | 'dark' | 'system'
  language?: string
  accentColor?: string
  tastes?: string[]
  dietaryRestrictions?: string[]
  budgetLevel?: string
  defaultCity?: string
}

export interface UserNotifications {
  push: boolean
  email: boolean
  newRecommendations: boolean
  weeklyDigest: boolean
}

export interface UserSettings {
  preferences?: UserPreferences
  notifications?: UserNotifications
  subscription?: {
    plan: string
    status: string
    expiresAt?: string | null
  }
}

export interface UserProfile {
  id: string
  name?: string
  username?: string
  email?: string
  location?: string
  avatar?: string
  stats?: {
    saved_count?: number
    search_count?: number
    visited_count?: number
  }
  preferences?: UserPreferences
  notifications?: UserNotifications
  subscription?: {
    plan: string
    status: string
    expiresAt?: string | null
  }
}

export interface InferredPreference {
  id: string
  category: string
  value: string
  confidence: number
  sourceSessionId?: string
  createdAt: string
}

export interface FaqItem {
  id: string
  question: string
  answer: string
  category: string
}

export interface FeedbackRequest {
  type: 'bug' | 'feature' | 'other'
  content: string
  contact?: string
}

export interface ObservabilityTask {
  task_id: string
  session_id?: string
  type: 'research' | 'refresh' | 'media'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  query?: string
  turn_count: number
  duration_ms: number
  retry_count: number
  recovery_state?: string
  error_reason?: string | null
  created_at: string
  updated_at: string
}

export interface QueryFamily {
  family_id: string
  pattern: string
  freshness_window_hours: number
  coverage_rate: number
  bundle_version: string
  watermark_updated_at: string
  stale_objects_count: number
  active_objects_count: number
}

export interface EvidenceBundle {
  bundle_id: string
  family_id: string
  version: string
  item_count: number
  sources_breakdown: Record<string, number>
  created_at: string
  checksum: string
}

export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  message?: string
  error?: string
  detail?: any
}
