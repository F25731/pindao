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
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
  NMenu, NButton, NSpace
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

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
</style>
