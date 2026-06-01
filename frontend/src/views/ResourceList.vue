<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-select v-model:value="statusFilter" :options="statusOptions" placeholder="按状态筛选" clearable style="width: 180px;" @update:value="loadData" />
      <n-input v-model:value="search" placeholder="搜名称/标签/源链接/新链接/错误" clearable style="width: 300px;" @clear="loadData" @keyup.enter="loadData" />
      <n-button @click="loadData">搜索</n-button>
    </n-space>

    <n-data-table :columns="columns" :data="resources" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />

    <n-space justify="center" style="margin-top: 16px;">
      <n-pagination v-model:page="page" :page-count="pageCount" @update:page="loadData" />
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { NDataTable, NSpace, NSelect, NInput, NButton, NPagination, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const resources = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 50
const statusFilter = ref<string | null>(null)
const search = ref('')

const pageCount = computed(() => Math.ceil(total.value / pageSize))

const statusOptions = [
  { label: '待转存', value: '待转存' },
  { label: '转存中', value: '转存中' },
  { label: '转存暂停', value: '转存暂停' },
  { label: '已取消', value: '已取消' },
  { label: '转存成功', value: '转存成功' },
  { label: '待推送', value: '待推送' },
  { label: '已推送', value: '已推送' },
  { label: '失败待重试', value: '失败待重试' },
  { label: '最终失败', value: '最终失败' },
  { label: '疑似重复待审核', value: '疑似重复待审核' },
  { label: '精确重复已跳过', value: '精确重复已跳过' },
  { label: '人工确认跳过', value: '人工确认跳过' },
]

const statusColorMap: Record<string, string> = {
  '待转存': 'default',
  '转存中': 'info',
  '转存暂停': 'warning',
  '已取消': 'default',
  '转存成功': 'success',
  '待推送': 'warning',
  '已推送': 'success',
  '失败待重试': 'error',
  '最终失败': 'error',
  '疑似重复待审核': 'warning',
}

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '名称', key: 'name', ellipsis: { tooltip: true }, width: 200 },
  { title: '标签', key: 'tags', width: 120, ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 130,
    render: (row: any) => h(NTag, { type: (statusColorMap[row.status] || 'default') as any, size: 'small' }, () => row.status)
  },
  { title: '源链接', key: 'original_link', width: 220, ellipsis: { tooltip: true } },
  { title: '新链接', key: 'new_share_link', width: 220, ellipsis: { tooltip: true } },
  { title: '错误', key: 'error_message', width: 150, ellipsis: { tooltip: true } },
  { title: '重试', key: 'retry_count', width: 50 },
  { title: '创建时间', key: 'created_at', width: 160, render: (row: any) => row.created_at?.slice(0, 19).replace('T', ' ') },
]

async function loadData() {
  loading.value = true
  try {
    const params: any = { page: page.value - 1, page_size: pageSize }
    if (statusFilter.value) params.status = statusFilter.value
    if (search.value) params.search = search.value
    const res = await api.get('/api/resources', { params })
    resources.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
