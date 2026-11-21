<script setup lang="ts">
// The one service page: five sections behind tabs. Only the visible section is mounted, so only its command is sent (lazy).
import { computed } from 'vue'
import { SECTIONS, hrefSection, type Route, type Section } from '../lib'
import ListPage from './ListPage.vue'
import StatusPage from './StatusPage.vue'

const props = defineProps<{ route: Route }>()
const section = computed(() => (props.route.params.section ?? 'snapshots') as Section)
const titles: Record<Section, string> = {
  snapshots: 'Снимки',
  sites: 'Сайты',
  discovery: 'Обнаружение',
  help: 'Справка',
  info: 'Информация',
}
</script>

<template>
  <section data-testid="page-service">
    <h1>Служебные</h1>
    <p class="tabs">
      <a v-for="name in SECTIONS" :key="name" :data-testid="'svc-tab-' + name" :href="hrefSection(name)" :aria-current="name === section ? 'page' : undefined">{{ titles[name] }}</a>
    </p>
    <ListPage v-if="section === 'snapshots' || section === 'sites'" :kind="section" :route="route" />
    <StatusPage v-else :kind="section" :route="route" />
  </section>
</template>
