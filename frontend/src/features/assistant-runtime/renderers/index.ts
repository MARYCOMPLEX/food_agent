import ResearchBlock from './ResearchBlock.vue'
import { createUiBlockRegistry } from '../rendererRegistry'
import type { AssistantUiBlockRendererEntry, AssistantUiBlockRegistry } from '../types'

const researchEntries: AssistantUiBlockRendererEntry[] = [
  'research.summary@1',
  'research.evidence@1',
  'research.controversy@1',
  'research.profile@1',
  'research.recommendation@1',
  'research.gap@1',
  'research.plan@1',
  'research.coverage@1',
].map(renderer => ({ renderer, component: ResearchBlock }))

export function createResearchUiBlockRegistry(): AssistantUiBlockRegistry {
  return createUiBlockRegistry(researchEntries)
}

export { ResearchBlock }
