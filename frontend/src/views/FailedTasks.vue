<template>
  <div>
    <n-space style="margin-bottom: 12px;" align="center">
      <n-tag type="warning">可重试失败: {{ queueStatus.failed_retryable || 0 }}</n-tag>
      <n-tag type="error">最终失败: {{ queueStatus.failed_final || 0 }}</n-tag>
      <n-tag type="info">已选: {{ selectedIds.length }}</n-tag>
    </n-space>

    <n-space style="margin-bottom: 16px;" align="center">
      <n-input
        v-model:value="search"
        clearable
        placeholder="搜索名称、源链接、错误原因"
        style="width: 320px;"
        @keyup.enter="reload"
      />
      <n-button :loading="loading" @click="loadData">刷新</n-button>
      <n-button type="primary" :disabled="!selectedIds.length" @click="batchRetry">
        批量重试
      </n-button>
      <n-button type="primary" secondary :disabled="!total" @click="retryAll">
        全部重试
      </n-button>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="tasks"
      :loading="loading"
      :pagination="false"
      :row-key="(r: any) => r.id"
      @update:checked-row-keys="(keys: any) => selectedIds = keys"
    />

    <n-space justify="center" style="margin-top: 16px;">
      <n-pagination v-model:page="page" :page-count="pageCount" @update:page="loadData" />
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { NDataTable, NSpace, NButton, NPagination, NTag, NInput, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const tasks = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 20
const selectedIds = ref<number[]>([])
const search = ref('')
const queueStatus = ref<Record<string, number>>({})

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const statusColorMap: Record<string, string> = {
  failed_retryable: 'warning',
  failed_final: 'error',
}

const columns = [
  { type: 'selection' as const },
  { title: '任务ID', key: 'id', width: 80 },
  { title: '资源ID', key: 'resource_id', width: 80 },
  { title: '名称', key: 'resource_name', minWidth: 220, ellipsis: { tooltip: true } },
  {
    title: '任务状态', key: 'status', width: 130,
    render: (row: any) => h(NTag, { type: (statusColorMap[row.status] || 'default') as any, size: 'small' }, () => row.status)
  },
  { title: '资源状态', key: 'resource_status', width: 120 },
  { title: '尝试次数', key: 'attempt', width: 90 },
  { title: '错误信息', key: 'error_message', minWidth: 260, ellipsis: { tooltip: true } },
  {
    title: '源链接',
    key: 'original_link',
    minWidth: 220,
    render: (row: any) => renderCopyText(row.original_link),
  },
  { title: '下次重试', key: 'next_retry_at', width: 160, render: (row: any) => row.next_retry_at?.slice(0, 19).replace('T', ' ') || '-' },
  {
    title: '操作', key: 'actions', width: 90,
    render: (row: any) => h(NButton, { size: 'small', type: 'primary', onClick: () => retryOne(row.id) }, () => '重试')
  },
]

async function retryOne(taskId: number) {
  try {
    const res = await api.post('/api/tasks/batch-retry', { task_ids: [taskId] })
    message.success(`已重试 ${res.data.updated || 0} 个任务`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '重试失败')
  }
}

async function batchRetry() {
  if (!selectedIds.value.length) return
  try {
    const res = await api.post('/api/tasks/batch-retry', { task_ids: selectedIds.value })
    message.success(`已重试 ${res.data.updated || 0} 个任务`)
    selectedIds.value = []
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '批量重试失败')
  }
}

async function retryAll() {
  if (!total.value) return
  if (!window.confirm(`确定重试全部 ${total.value} 个失败任务？`)) return
  try {
    const res = await api.post('/api/tasks/failed/retry-all')
    message.success(`已重试 ${res.data.updated || 0} 个任务`)
    selectedIds.value = []
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '全部重试失败')
  }
}

async function copyText(text?: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制链接')
  } catch {
    const input = document.createElement('textarea')
    input.value = text
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    message.success('已复制链接')
  }
}

function renderCopyText(text?: string) {
  if (!text) return '-'
  return h('button', { class: 'copy-link', onClick: () => copyText(text), title: '点击复制' }, text)
}

function reload() {
  page.value = 1
  loadData()
}

async function loadData() {
  loading.value = true
  try {
    const [tasksRes, statusRes] = await Promise.all([
      api.get('/api/tasks/failed', {
        params: {
          page: page.value - 1,
          page_size: pageSize,
          search: search.value || undefined,
        },
      }),
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

<style scoped>
.copy-link {
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
