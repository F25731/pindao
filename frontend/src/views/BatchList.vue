<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button @click="loadData">刷新</n-button>
      <n-button type="error" :disabled="!selectedIds.length" @click="deleteSelected">批量彻底删除</n-button>
    </n-space>
    <n-data-table
      :columns="columns"
      :data="batches"
      :loading="loading"
      :pagination="false"
      :row-key="(r: any) => r.id"
      @update:checked-row-keys="(keys: any) => selectedIds = keys"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NButton, NDataTable, NSpace, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const batches = ref<any[]>([])
const loading = ref(false)
const selectedIds = ref<number[]>([])

const columns = [
  { type: 'selection' as const },
  { title: 'ID', key: 'id', width: 60 },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true } },
  { title: '总行数', key: 'total_rows', width: 80 },
  { title: '新增', key: 'new_count', width: 70 },
  { title: '重复跳过', key: 'duplicate_skipped', width: 90 },
  { title: '疑似重复', key: 'fuzzy_flagged', width: 90 },
  { title: '解析失败', key: 'parse_failed', width: 90 },
  {
    title: '状态', key: 'status', width: 100,
    render: (row: any) => h(NTag, { type: row.status === 'completed' ? 'success' : 'warning', size: 'small' }, () => row.status)
  },
  { title: '创建时间', key: 'created_at', width: 170, render: (row: any) => row.created_at?.slice(0, 19).replace('T', ' ') },
  {
    title: '操作', key: 'actions', width: 100,
    render: (row: any) => h(NButton, { size: 'small', type: 'error', ghost: true, onClick: () => deleteOne(row.id) }, () => '彻底删除')
  },
]

async function loadData() {
  loading.value = true
  try {
    const res = await api.get('/api/imports/batches')
    batches.value = res.data
    selectedIds.value = []
  } finally {
    loading.value = false
  }
}

async function deleteOne(id: number) {
  if (!window.confirm(`确定彻底删除批次 #${id}？该批次下所有资源、任务、推送记录、重复审核都会删除。`)) return
  try {
    const res = await api.delete(`/api/imports/batches/${id}`)
    message.success(`已删除批次 ${res.data.deleted_batches || 0} 个，资源 ${res.data.deleted_resources || 0} 条`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '删除失败')
  }
}

async function deleteSelected() {
  if (!selectedIds.value.length) return
  if (!window.confirm(`确定彻底删除选中的 ${selectedIds.value.length} 个批次？批次下所有资源、任务、推送记录、重复审核都会删除。`)) return
  try {
    const res = await api.post('/api/imports/batches/batch-delete', { batch_ids: selectedIds.value })
    message.success(`已删除批次 ${res.data.deleted_batches || 0} 个，资源 ${res.data.deleted_resources || 0} 条`)
    selectedIds.value = []
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '批量删除失败')
  }
}

onMounted(loadData)
</script>
