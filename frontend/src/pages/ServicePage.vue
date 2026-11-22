<script setup lang="ts">
// The one service page: six sections behind a toolbar of button-like links. Only the visible section is mounted, so only its command is sent (lazy).
import { computed } from 'vue'
import { SECTIONS, hrefSection, type Route, type Section } from '../lib'
import ListPage from './ListPage.vue'
import SchedulePage from './SchedulePage.vue'
import StatusPage from './StatusPage.vue'

const props = defineProps<{ route: Route }>()
const section = computed(() => (props.route.params.section ?? 'snapshots') as Section)
const titles: Record<Section, string> = {
  snapshots: 'Снимки',
  sites: 'Сайты',
  discovery: 'Обнаружение',
  help: 'Справка',
  info: 'Информация',
  schedule: 'Расписание',
}
</script>

<template>
  <section data-testid="page-service">
    <h1>Служебные</h1>
    <nav data-testid="svc-toolbar" class="svc-toolbar" aria-label="Разделы">
      <a v-for="name in SECTIONS" :key="name" :data-testid="'svc-tab-' + name" :href="hrefSection(name)" :aria-current="name === section ? 'page' : undefined">{{ titles[name] }}</a>
    </nav>
    <ListPage v-if="section === 'snapshots' || section === 'sites'" :kind="section" :route="route" />
    <SchedulePage v-else-if="section === 'schedule'" />
    <StatusPage v-else :kind="section" :route="route" />
  </section>
</template>

<style scoped>
.svc-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.5rem 0 1rem;
}
.svc-toolbar a {
  display: inline-flex;
  align-items: center;
  box-sizing: border-box;
  min-height: 28px;
  padding: 0.25rem 0.9rem;
  border: 1px solid #8c959f;
  border-radius: 4px;
  background: #f6f8fa;
  color: #0969da;
  text-decoration: none;
}
.svc-toolbar a:hover {
  background: #eaeef2;
}
.svc-toolbar a[aria-current='page'] {
  border-color: #0969da;
  background: #0969da;
  color: #fff;
  font-weight: 600;
}
</style>
