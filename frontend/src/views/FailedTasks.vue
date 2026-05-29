<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button type="primary" :disabled="!selectedIds.length" @click="batchRetry">批量重试 ({{ selectedIds.length }})</n-button>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="resources"
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
import { NDataTable, NSpace, NButton, NPagination, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const resources = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 20
const selectedIds = ref<number[]>([])

const pageCount = computed(() => Math.ceil(total.value / pageSize))

const columns = [
  { type: 'selection' as const },
  { title: 'ID', key: 'id', width: 60 },
  { title: '名称', key: 'name', ellipsis: { tooltip: true }, width: 200 },
  {
    title: '状态', key: 'status', width: 120,
    render: (row: any) => h(NTag, { type: 'error', size: 'small' }, () => row.status)
  },
  { title: '错误信息', key: 'error_message', ellipsis: { tooltip: true } },
  { title: '重试次数', key: 'retry_count', width: 80 },
  { title: '创建时间', key: 'created_at', width: 160, render: (row: any) => row.created_at?.slice(0, 19).replace('T', ' ') },
  {
    title: '操作', key: 'actions', width: 80,
    render: (row: any) => h(NButton, { size: 'small', type: 'primary', onClick: () => retryOne(row.id) }, () => '重试')
  },
]

async function retryOne(id: number) {
  try {
    await api.post(`/api/resources/${id}/retry`)
    message.success('已重置为待转存')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '重试失败')
  }
}

async function batchRetry() {
  if (!selectedIds.value.length) return
  try {
    const res = await api.post('/api/resources/batch-retry', selectedIds.value)
    message.success(`已重试 ${res.data.retried} 条`)
    selectedIds.value = []
    loadData()
  } catch (e: any) {
    message.error('批量重试失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.get('/api/resources', {
      params: { page: page.value - 1, page_size: pageSize, status: '最终失败' }
    })
    resources.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
