<script setup lang="ts">
import type { Restaurant } from '../types'
import AdaptiveCard from '../../../shared/ui/AdaptiveCard.vue'
import TrustScoreBadge from './TrustScoreBadge.vue'
import MustTryList from './MustTryList.vue'
import ConsWarning from './ConsWarning.vue'

defineProps<{
  restaurant: Restaurant
  isFavorite?: boolean
}>()

const emit = defineEmits<{
  (e: 'click', restaurant: Restaurant): void
  (e: 'toggleFavorite', restaurant: Restaurant): void
}>()
</script>

<template>
  <AdaptiveCard
    :interactive="true"
    padding="md"
    class="flex flex-col justify-between group hover:border-[var(--color-brand-400)] transition-all"
    @click="emit('click', restaurant)"
  >
    <div>
      <!-- Header with Name, Badge and Favorite -->
      <div class="flex items-start justify-between gap-2 mb-2">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <h4 class="font-bold text-base md:text-lg text-[var(--color-text-primary)] group-hover:text-[var(--color-brand-600)] transition-colors truncate">
              {{ restaurant.name }}
            </h4>
            <span v-if="restaurant.chnName && restaurant.chnName !== restaurant.name" class="text-xs text-[var(--color-text-tertiary)]">
              ({{ restaurant.chnName }})
            </span>
          </div>

          <div class="flex items-center gap-2 mt-1 text-xs text-[var(--color-text-secondary)]">
            <span v-if="restaurant.price" class="font-mono font-medium text-[var(--color-brand-600)]">
              {{ restaurant.price }}
            </span>
            <span v-if="restaurant.distance" class="text-[var(--color-text-tertiary)]">
              · 距离 {{ restaurant.distance }}
            </span>
            <span v-if="restaurant.authenticity" class="px-1.5 py-0.2 rounded bg-indigo-50 text-indigo-700 text-[11px]">
              {{ restaurant.authenticity === 'authentic' ? '本地老店' : restaurant.authenticity }}
            </span>
          </div>
        </div>

        <div class="flex items-center gap-1.5 shrink-0">
          <TrustScoreBadge :score="restaurant.trustScore || 7.0" size="sm" />
          <button
            class="p-1.5 rounded-full text-base transition-transform active:scale-125 cursor-pointer hover:bg-[var(--color-neutral-150)]"
            :class="isFavorite ? 'text-red-500' : 'text-[var(--color-neutral-400)] hover:text-red-400'"
            @click.stop="emit('toggleFavorite', restaurant)"
          >
            {{ isFavorite ? '❤️' : '🤍' }}
          </button>
        </div>
      </div>

      <!-- One Liner Summary -->
      <p v-if="restaurant.oneLiner" class="text-xs md:text-sm text-[var(--color-text-secondary)] mb-3 line-clamp-2 leading-relaxed">
        {{ restaurant.oneLiner }}
      </p>

      <!-- Tags -->
      <div v-if="restaurant.tags && restaurant.tags.length" class="flex flex-wrap gap-1 mb-3">
        <span
          v-for="tag in restaurant.tags.slice(0, 4)"
          :key="tag"
          class="px-2 py-0.5 rounded-md text-[11px] bg-[var(--color-neutral-150)] text-[var(--color-text-secondary)]"
        >
          #{{ tag }}
        </span>
      </div>

      <!-- Must Try / Warnings snippet -->
      <div class="space-y-2 mb-2">
        <MustTryList v-if="restaurant.mustTry && restaurant.mustTry.length" :items="restaurant.mustTry.slice(0, 2)" />
        <ConsWarning v-if="restaurant.warning" :warning="restaurant.warning" />
      </div>
    </div>

    <!-- Card Footer -->
    <div class="pt-2 border-t border-[var(--color-border)] flex items-center justify-between text-xs text-[var(--color-text-tertiary)] mt-2">
      <span v-if="restaurant.sourceNotesCount">基于 {{ restaurant.sourceNotesCount }} 篇笔记综合研判</span>
      <span v-else>综合多维度数据研判</span>
      <span class="text-[var(--color-brand-600)] font-medium group-hover:translate-x-0.5 transition-transform">
        查看证据详情 →
      </span>
    </div>
  </AdaptiveCard>
</template>
