<script setup lang="ts">
import type { ResearchProfileViewV1 } from '../../../../shared/contracts/research'
import { computed } from 'vue'
import { dishLabel, formatCount, imageUrl, sourceLabel } from './researchFormat'

const props = withDefaults(defineProps<{
  profiles: ResearchProfileViewV1[]
  loading?: boolean
}>(), { loading: false })

const profileImages = computed(() => new Map(props.profiles.map(profile => [profile.profileId, profile.images?.map(imageUrl).find(Boolean) ?? profile.imageUrl ?? null])))

function dishNames(profile: ResearchProfileViewV1): string[] {
  return (profile.recommendedDishes ?? [])
    .slice(0, 4)
    .map(dishLabel)
    .filter((dish): dish is string => Boolean(dish))
}

function profileStatus(status: ResearchProfileViewV1['status']): string {
  return status === 'complete' ? '档案完整' : status === 'partial' ? '资料部分补齐' : status === 'failed' ? '补充失败' : status === 'unavailable' ? '暂无资料' : '待补充'
}
</script>

<template>
  <section class="research-panel research-profile-panel" aria-labelledby="research-profile-title">
    <div class="research-panel-heading research-panel-heading-wrap">
      <div>
        <p class="research-kicker">PLACE INTELLIGENCE</p>
        <h2 id="research-profile-title" class="research-panel-title">店铺档案</h2>
        <p class="research-panel-subtitle">用平台结构化信息补齐地址、价格、招牌菜和到店决策所需的细节。</p>
      </div>
      <span class="research-count-badge research-count-badge-cool">{{ profiles.length }} 家</span>
    </div>

    <div v-if="loading && !profiles.length" class="research-profile-grid" aria-label="店铺档案加载中" aria-busy="true">
      <div v-for="index in 2" :key="index" class="research-profile-skeleton" />
    </div>
    <div v-else-if="!profiles.length" class="research-empty-inline">
      <span class="research-empty-glyph" aria-hidden="true">⌂</span>
      <span>店铺档案将在识别到候选实体后补齐</span>
    </div>
    <div v-else class="research-profile-grid">
      <article v-for="profile in profiles" :key="profile.profileId" class="research-profile-card">
        <div class="research-profile-hero">
          <img v-if="profileImages.get(profile.profileId)" :src="profileImages.get(profile.profileId) ?? undefined" :alt="`${profile.name ?? '店铺'}图片`" loading="lazy">
          <div v-else class="research-profile-image-placeholder" aria-hidden="true">⌂</div>
          <span class="research-profile-status" :class="`is-${profile.status ?? 'pending'}`">{{ profileStatus(profile.status) }}</span>
        </div>
        <div class="research-profile-body">
          <div class="research-profile-title-row">
            <div>
              <h3>{{ profile.name || '未命名店铺' }}</h3>
              <p v-if="profile.alias">{{ profile.alias }}</p>
            </div>
            <div v-if="profile.rating !== null && profile.rating !== undefined" class="research-rating" aria-label="评分">
              <strong>{{ profile.rating.toFixed(1) }}</strong><span>/10</span>
            </div>
          </div>
          <div class="research-profile-facts">
            <span v-if="profile.averagePrice !== null && profile.averagePrice !== undefined">人均 ¥{{ profile.averagePrice }}</span>
            <span v-if="profile.reviewCount !== null && profile.reviewCount !== undefined">{{ formatCount(profile.reviewCount) }} 条评价</span>
            <span v-if="profile.category">{{ profile.category }}</span>
          </div>
          <p v-if="profile.address || profile.location" class="research-profile-address">{{ profile.address || profile.location }}</p>
          <div v-if="profile.recommendedDishes?.length" class="research-dish-list">
            <span class="research-detail-label">值得留意</span>
            <span v-for="dish in dishNames(profile)" :key="dish" class="research-dish-chip">{{ dish }}</span>
          </div>
          <div v-if="profile.tags?.length" class="research-tag-list">
            <span v-for="tag in profile.tags.slice(0, 4)" :key="tag">#{{ tag }}</span>
          </div>
          <div class="research-profile-footer">
            <span v-if="profile.providerRefs && Object.keys(profile.providerRefs).length">{{ sourceLabel(Object.keys(profile.providerRefs)[0]) }} 已核验</span>
            <span v-if="profile.gapRefs?.length" class="research-gap-note">缺 {{ profile.gapRefs.length }} 项资料</span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
