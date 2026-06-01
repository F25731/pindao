<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button :loading="loading" @click="loadData">刷新</n-button>
      <n-button type="warning" :loading="loading" @click="recoverStuck">恢复卡住的推送</n-button>
      <n-button type="primary" :loading="loading" @click="requeueFailed">失败重新入队</n-button>
      <n-button :loading="loading" @click="requeueSentTest">已推送抽 3 条测试</n-button>
      <n-button type="error" ghost :loading="loading" @click="requeueAllSent">全部已推送重新入队</n-button>
    </n-space>

    <n-grid :cols="4" :x-gap="16" style="margin-bottom: 16px;">
      <n-gi v-for="(value, key) in pushStats" :key="key">
        <n-card size="small">
          <n-statistic :label="key" :value="value" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-card title="待推送资源">
      <n-data-table :columns="columns" :data="pendingList" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NGrid, NGi, NCard, NStatistic, NDataTable, NButton, NSpace, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const pushStats = ref<Record<string, number>>({})
const pendingList = ref<any[]>([])
const loading = ref(false)

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '标签', key: 'tags', width: 120, ellipsis: { tooltip: true } },
  { title: '新链接', key: 'new_share_link', width: 250, ellipsis: { tooltip: true } },
  { title: '转存时间', key: 'transferred_at', width: 160, render: (row: any) => row.transferred_at?.slice(0, 19).replace('T', ' ') || '-' },
]

async function loadData() {
  loading.value = true
  try {
    const [statsRes, pendingRes] = await Promise.all([
      api.get('/api/telegram/stats'),
      api.get('/api/telegram/pending', { params: { page: 0, page_size: 50 } }),
    ])
    pushStats.value = statsRes.data
    pendingList.value = pendingRes.data.items || []
  } finally {
    loading.value = false
  }
}

async function recoverStuck() {
  try {
    const res = await api.post('/api/telegram/recover-stuck', null, { params: { minutes: 30 } })
    message.success(`已恢复 ${res.data.recovered || 0} 条`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '恢复失败')
  }
}

async function requeueFailed() {
  try {
    const res = await api.post('/api/telegram/requeue', { statuses: ['推送失败待重试', '推送最终失败'] })
    message.success(`已重新入队 ${res.data.queued || 0} 条`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '重新入队失败')
  }
}

async function requeueSentTest() {
  try {
    const res = await api.post('/api/telegram/requeue', { statuses: ['已推送'], limit: 3 })
    message.success(`已重新入队 ${res.data.queued || 0} 条，可用 /gy_push_once 测试`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '测试入队失败')
  }
}

async function requeueAllSent() {
  if (!window.confirm('会把所有已推送资源改回待推送，用于换频道后全量补推。确定继续？')) return
  try {
    const res = await api.post('/api/telegram/requeue', { statuses: ['已推送'] })
    message.success(`已重新入队 ${res.data.queued || 0} 条`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '全量入队失败')
  }
}

onMounted(loadData)
</script>
