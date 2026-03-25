import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: 'Investigation' },
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('@/views/SessionSetupView.vue'),
    meta: { title: 'Session Setup' },
  },
  {
    // Catch-all 404
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '404' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
})

router.afterEach((to) => {
  const title = to.meta['title'] as string | undefined
  document.title = title ? `${title} — Grafana AI Agent` : 'Grafana AI Agent'
})

export default router
