<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      :width="220"
    >
      <div class="logo">
        <span>光鸭资源管理</span>
      </div>
      <n-menu
        :options="menuOptions"
        :value="currentRoute"
        @update:value="handleMenuClick"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px;">
        <span style="font-size: 16px; font-weight: 500;">{{ pageTitle }}</span>
        <n-space align="center">
          <n-tag v-if="systemControl.worker_paused" type="error" size="small">全局已暂停</n-tag>
          <span class="control-label">线程</span>
          <n-input-number
            v-model:value="concurrencyValue"
            size="small"
            :min="1"
            :max="10"
            :show-button="false"
            style="width: 72px;"
          />
          <n-button
            size="small"
            :loading="concurrencyLoading"
            @click="saveConcurrency"
          >
            应用
          </n-button>
          <n-button
            size="small"
            :type="systemControl.worker_paused ? 'primary' : 'warning'"
            :loading="systemActionLoading"
            @click="toggleSystemPause"
          >
            {{ systemControl.worker_paused ? '恢复系统' : '全局暂停' }}
          </n-button>
          <span>{{ authStore.username }}</span>
          <n-button size="small" @click="handleLogout">退出</n-button>
        </n-space>
      </n-layout-header>
      <n-layout-content style="padding: 24px; overflow: auto; height: calc(100vh - 56px);">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
  NMenu, NButton, NSpace, NTag, NInputNumber, useMessage
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { api } from '../api/client'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const message = useMessage()
const systemActionLoading = ref(false)
const concurrencyLoading = ref(false)
const concurrencyValue = ref(2)
const systemControl = ref({
  worker_paused: false,
  reason: '',
  max_concurrent: 2,
  running_tasks: 0,
  pending_tasks: 0,
  paused_tasks: 0,
})

const currentRoute = computed(() => route.name as string)

const pageTitles: Record<string, string> = {
  Dashboard: '运行统计',
  ImportExcel: 'Excel 导入',
  BatchList: '导入批次',
  ResourceList: '资源列表',
  ResourceSearch: '资源检索',
  TaskQueue: '任务队列',
  FailedTasks: '失败任务',
  AccountPool: '账号池管理',
  ExportExcel: '导出 Excel',
  TelegramPush: '推送管理',
  ApiKeys: 'API 密钥',
  Stats: '详细统计',
}

const pageTitle = computed(() => pageTitles[route.name as string] || '管理后台')

const menuOptions: MenuOption[] = [
  { label: '运行统计', key: 'Dashboard' },
  { label: 'Excel 导入', key: 'ImportExcel' },
  { label: '导入批次', key: 'BatchList' },
  { label: '资源列表', key: 'ResourceList' },
  { label: '资源检索', key: 'ResourceSearch' },
  { label: '任务队列', key: 'TaskQueue' },
  { label: '失败任务', key: 'FailedTasks' },
  { label: '账号池', key: 'AccountPool' },
  { label: '导出 Excel', key: 'ExportExcel' },
  { label: '推送管理', key: 'TelegramPush' },
  { label: 'API 密钥', key: 'ApiKeys' },
]

function handleMenuClick(key: string) {
  router.push({ name: key })
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

async function loadSystemControl() {
  try {
    const res = await api.get('/api/system/control')
    systemControl.value = res.data
    concurrencyValue.value = res.data.max_concurrent || 2
  } catch (e) {
    console.error('加载系统控制状态失败', e)
  }
}

async function saveConcurrency() {
  concurrencyLoading.value = true
  try {
    const value = Math.max(1, Math.min(Number(concurrencyValue.value || 1), 10))
    const res = await api.post('/api/system/concurrency', { max_concurrent: value })
    systemControl.value = { ...systemControl.value, max_concurrent: res.data.max_concurrent }
    concurrencyValue.value = res.data.max_concurrent
    message.success(`转存线程数已设置为 ${res.data.max_concurrent}，worker 将实时按新值调度`)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '设置线程数失败')
  } finally {
    concurrencyLoading.value = false
  }
}

async function toggleSystemPause() {
  systemActionLoading.value = true
  try {
    if (systemControl.value.worker_paused) {
      await api.post('/api/system/resume')
      message.success('系统已恢复，worker 会继续处理导入和转存')
    } else {
      const res = await api.post('/api/system/pause', { reason: '后台全局暂停' })
      message.success(`已全局暂停：暂停 ${res.data.paused || 0} 个任务，等待停止 ${res.data.pause_requested || 0} 个`)
    }
    await loadSystemControl()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '系统控制失败')
  } finally {
    systemActionLoading.value = false
  }
}

onMounted(loadSystemControl)
</script>

<style scoped>
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: bold;
  border-bottom: 1px solid var(--n-border-color);
}

.control-label {
  color: #666;
  font-size: 13px;
}
</style>
