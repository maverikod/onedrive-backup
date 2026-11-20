<script setup lang="ts">
import type { Banner } from '../command'

defineProps<{ banner: Banner | null }>()
</script>

<template>
  <div v-if="banner" data-testid="error-banner" role="alert">
    <strong data-testid="error-code" :data-raw="String(banner.code)">{{ banner.code }}</strong>
    <span data-testid="error-message">{{ banner.message }}</span>
  </div>
</template>
