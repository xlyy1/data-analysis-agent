import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** auth = 登录页，不套侧边栏壳 */
    layout?: 'app' | 'auth'
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue'),
      meta: { layout: 'auth', title: '登录' },
    },
    {
      path: '/',
      name: 'Chat',
      component: () => import('../views/ChatView.vue'),
      meta: { layout: 'app', title: '对话分析' },
    },
    {
      path: '/datasources',
      name: 'DataSources',
      component: () => import('../views/DataSourcesView.vue'),
      meta: { layout: 'app', title: '数据源' },
    },
    {
      path: '/reports',
      name: 'Reports',
      component: () => import('../views/ReportsView.vue'),
      meta: { layout: 'app', title: '分析报告' },
    },
    {
      path: '/schedules',
      name: 'Schedules',
      component: () => import('../views/SchedulesView.vue'),
      meta: { layout: 'app', title: '定时分析' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

/** 除 /login 外全部需要登录；已登录访问 /login 直接回首页。 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.name === 'Login') {
    if (auth.isAuthenticated) {
      const ready = auth.user ? true : await auth.restore()
      if (ready) return { path: '/' }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    const ready = await auth.restore()
    if (!ready) return { name: 'Login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title
  document.title = title ? `${title} · DataAgent` : 'DataAgent · AI 数据分析师'
})

export default router
