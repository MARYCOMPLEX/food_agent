import type {
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
} from '../../shared/contracts/research'

export type AttachedContext = { type: 'shop' | 'controversy'; title: string } | null

export type RightPanelTab = 'evidence' | 'controversies' | 'profile'

export interface ChatTurn {
  id: string
  turnId: number
  userMessage: {
    content: string
    attachedContext?: AttachedContext
    createdAt: string
  }
  assistantMessage: {
    summary: string
    plan?: Array<{
      id: string
      label: string
      status: 'loading' | 'running' | 'succeeded' | 'failed' | 'idle'
      detail?: string
    }>
    recommendations?: any[]
    controversies?: any[]
    profiles?: any[]
    evidence?: any[]
    isRunning?: boolean
    statusMessage?: string
    error?: string
    createdAt: string
  }
}

export interface ModelOption {
  value: string
  label: string
  is_default: boolean
  provider?: string
  model_id?: string
}

export interface SharedWorkbenchProps {
  // Session & turns
  currentSessionId: string
  sessionTurns: ChatTurn[]
  isRunning: boolean
  isNewSession: boolean

  // Inputs & Actions
  inputText: string
  setInputText: (text: string) => void
  isInputFocused: boolean
  setIsInputFocused: (focused: boolean) => void
  attachedContext: AttachedContext
  setAttachedContext: (ctx: AttachedContext) => void
  handleSendMessage: (overrideText?: string) => void
  handleStopInvestigation: () => void
  handleStartNewChat: () => void
  handleRetryLastTurn: () => void

  // History sessions
  historyList: any[]
  handleSelectSession: (sid: string) => void
  handleDeleteSession: (sid: string, e: React.MouseEvent) => void

  // Models & MCP
  selectedModel: string
  setSelectedModel: (m: string) => void
  modelOptions: ModelOption[]
  mcpServices: any[]

  // Compare & Favorites
  compareList: any[]
  setCompareList: (list: any[]) => void
  favorites: string[]
  isCompareModalOpen: boolean
  setIsCompareModalOpen: (open: boolean) => void
  handleAddToCompare: (rec: any, profile: any) => void
  handleRemoveFromCompare: (recId: string) => void
  handleToggleFavorite: (recId: string, title?: string) => void

  // Platform Accounts & Login
  accounts: any
  setAccounts: (acc: any) => void
  loginModalPlatform: 'xhs_pc' | 'dianping' | null
  setLoginModalPlatform: (p: 'xhs_pc' | 'dianping' | null) => void
  rightPanelOpen: boolean
  setRightPanelOpen: (open: boolean) => void
  rightPanelTab: RightPanelTab
  setRightPanelTab: (tab: RightPanelTab) => void
  openInspector: (tab: RightPanelTab) => void
  selectedProfile: ResearchProfileViewV1 | null
  selectedRec: ResearchRecommendationViewV1 | null
  isProfileDrawerOpen: boolean
  setIsProfileDrawerOpen: (open: boolean) => void
  openStandaloneProfile: (profile: any, rec: any) => void

  // Feedback & suggestions
  feedbackRating: 'up' | 'down' | null
  setFeedbackRating: (rating: 'up' | 'down' | null) => void
  hasCopied: boolean
  handleCopyResponse: (text: string, query: string) => void
  suggestions: string[]

  // Auth & QR
  isQrModalOpen: boolean
  setIsQrModalOpen: (open: boolean) => void

  // Derived data
  recommendations: any[]
  evidenceItems: any[]
  controversies: any[]
  profiles: any[]
  plan: any[]
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void

  // DOM Refs
  chatBottomRef: React.RefObject<any>
  textareaRef: React.RefObject<any>
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
}
