<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-tag type="info">Pending: {{ queueStatus.pending || 0 }}</n-tag>
      <n-tag type="warning">Running: {{ queueStatus.running || 0 }}</n-tag>
      <n-tag type="default">Paused: {{ queueStatus.paused || 0 }}</n-tag>
      <n-tag type="error">Failed Retryable: {{ queueStatus.failed_retryable || 0 }}</n-tag>
    </n-space>

    <n-data-table :columns="columns" :data="tasks" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />

    <n-space justify="center" style="margin-top: 16px;">
      <n-pagination v-model:page="page" :page-count="pageCount" @update:page="loadData" />
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { NDataTable, NSpace, NTag, NPagination, NButton, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const tasks = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 20
const queueStatus = ref<Record<string, number>>({})

const pageCount = computed(() => Math.ceil(total.value / pageSize))

const statusColorMap: Record<string, string> = {
  pending: 'default',
  running: 'info',
  pause_requested: 'warning',
  paused: 'default',
  cancel_requested: 'warning',
  success: 'success',
  failed_retryable: 'warning',
  failed_final: 'error',
  skipped: 'default',
  waiting_review: 'warning',
}

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '资源ID', key: 'resource_id', width: 80 },
  { title: '类型', key: 'task_type', width: 80 },
  {
    title: '状态', key: 'status', width: 130,
    render: (row: any) => h(NTag, { type: (statusColorMap[row.status] || 'default') as any, size: 'small' }, () => row.status)
  },
  { title: '尝试次数', key: 'attempt', width: 80 },
  { title: '错误信息', key: 'error_message', width: 200, ellipsis: { tooltip: true } },
  { title: '开始时间', key: 'started_at', width: 160, render: (row: any) => row.started_at?.slice(0, 19).replace('T', ' ') || '-' },
  { title: '下次重试', key: 'next_retry_at', width: 160, render: (row: any) => row.next_retry_at?.slice(0, 19).replace('T', ' ') || '-' },
  {
    title: '操作', key: 'actions', width: 160,
    render: (row: any) => {
      const buttons = []
      if (row.status === 'pending' || row.status === 'running' || row.status === 'failed_retryable') {
        buttons.push(h(NButton, { size: 'small', type: 'warning', onClick: () => pauseTask(row.id) }, () => '暂停'))
      }
      if (row.status === 'paused' || row.status === 'pause_requested') {
        buttons.push(h(NButton, { size: 'small', type: 'primary', onClick: () => resumeTask(row.id) }, () => '恢复'))
      }
      if (row.status === 'pending' || row.status === 'running') {
        buttons.push(h(NButton, { size: 'small', type: 'error', onClick: () => cancelTask(row.id) }, () => '取消'))
      }
      return buttons.length ? h(NSpace, { size: 6 }, () => buttons) : '-'
    }
  },
]

async function pauseTask(taskId: number) {
  try {
    await api.post(`/api/tasks/${taskId}/pause`)
    message.success('已暂停')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '暂停失败')
  }
}

async function resumeTask(taskId: number) {
  try {
    await api.post(`/api/tasks/${taskId}/resume`)
    message.success('已恢复')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '恢复失败')
  }
}

async function cancelTask(taskId: number) {
  try {
    await api.post(`/api/tasks/${taskId}/cancel`)
    message.success('已取消')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '取消失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const [tasksRes, statusRes] = await Promise.all([
      api.get('/api/tasks', { params: { page: page.value - 1, page_size: pageSize } }),
      api.get('/api/tasks/queue-status'),
    ])
    tasks.value = tasksRes.data.items
    total.value = tasksRes.data.total
    queueStatus.value = statusRes.data
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
