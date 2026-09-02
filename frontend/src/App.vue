<script setup lang="ts">
import { NConfigProvider } from 'naive-ui'
import { RouterView } from 'vue-router'
import { themeOverrides } from './theme'
</script>

<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <RouterView />
  </NConfigProvider>
</template>
