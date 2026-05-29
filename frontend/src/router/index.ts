import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
  },
  {
    path: '/',
    component: () => import('../components/Layout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'import', name: 'ImportExcel', component: () => import('../views/ImportExcel.vue') },
      { path: 'batches', name: 'BatchList', component: () => import('../views/BatchList.vue') },
      { path: 'resources', name: 'ResourceList', component: () => import('../views/ResourceList.vue') },
      { path: 'tasks', name: 'TaskQueue', component: () => import('../views/TaskQueue.vue') },
      { path: 'duplicates', name: 'DuplicateReview', component: () => import('../views/DuplicateReview.vue') },
      { path: 'failed', name: 'FailedTasks', component: () => import('../views/FailedTasks.vue') },
      { path: 'accounts', name: 'AccountPool', component: () => import('../views/AccountPool.vue') },
      { path: 'export', name: 'ExportExcel', component: () => import('../views/ExportExcel.vue') },
      { path: 'telegram', name: 'TelegramPush', component: () => import('../views/TelegramPush.vue') },
      { path: 'api-keys', name: 'ApiKeys', component: () => import('../views/ApiKeys.vue') },
      { path: 'stats', name: 'Stats', component: () => import('../views/Stats.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.token) {
    next('/login')
  } else {
    next()
  }
})

export default router
