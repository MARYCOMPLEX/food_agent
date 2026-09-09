import type {
  ResearchControversyViewV1,
  ResearchCoverageViewV1,
  ResearchEvidenceItemV1,
  ResearchGapViewV1,
  ResearchMetricsV1,
  ResearchPlanStepViewV1,
  ResearchProfileViewV1,
  ResearchRecommendationViewV1,
  ResearchRunStatusV1,
  UserResearchProjectionV1,
} from '../../../../shared/contracts/research'

export type ResearchSurfaceState = 'loading' | 'error' | 'empty' | 'ready'

export interface ResearchSurfaceProps {
  projection?: UserResearchProjectionV1 | null
  evidence?: ResearchEvidenceItemV1[]
  controversies?: ResearchControversyViewV1[]
  profiles?: ResearchProfileViewV1[]
  recommendations?: ResearchRecommendationViewV1[]
  gaps?: ResearchGapViewV1[]
  plan?: ResearchPlanStepViewV1[]
  coverage?: ResearchCoverageViewV1 | null
  metrics?: ResearchMetricsV1
  status?: ResearchRunStatusV1
  phase?: string | null
  summary?: string | null
  loading?: boolean
  error?: string | null
}

export type ResearchSurfaceProjection = Pick<
  UserResearchProjectionV1,
  'evidence' | 'controversies' | 'profiles' | 'recommendations' | 'gaps' | 'plan'
>
