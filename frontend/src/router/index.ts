import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Chat',
      component: () => import('../views/ChatView.vue'),
    },
    {
      path: '/datasources',
      name: 'DataSources',
      component: () => import('../views/DataSourcesView.vue'),
    },
    {
      path: '/reports',
      name: 'Reports',
      component: () => import('../views/ReportsView.vue'),
    },
  ],
})

export default router
