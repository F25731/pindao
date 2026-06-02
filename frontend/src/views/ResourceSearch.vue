<template>
  <div>
    <n-space style="margin-bottom: 16px;" align="center">
      <n-input
        v-model:value="search"
        placeholder="输入关键词搜索名称、标签、源链接、我的分享链接"
        clearable
        style="width: 420px;"
        @keyup.enter="searchResources"
        @clear="searchResources"
      />
      <n-select
        v-model:value="statusFilter"
        :options="statusOptions"
        placeholder="状态"
        clearable
        style="width: 160px;"
        @update:value="searchResources"
      />
      <n-button type="primary" :loading="loading" @click="searchResources">搜索</n-button>
      <n-button :loading="loading" @click="loadData">刷新</n-button>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="resources"
      :loading="loading"
      :pagination="false"
      :row-key="(r: any) => r.id"
    />

    <n-space justify="space-between" align="center" style="margin-top: 16px;">
      <span style="color: #666;">共 {{ total }} 条</span>
      <n-pagination v-model:page="page" :page-count="pageCount" @update:page="loadData" />
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { NButton, NDataTable, NInput, NPagination, NSelect, NSpace } from 'naive-ui'
import { api } from '../api/client'

const resources = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 50
const search = ref('')
const statusFilter = ref<string | null>(null)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const statusOptions = [
  { label: '待推送', value: '待推送' },
  { label: '推送队列', value: '推送队列' },
  { label: '推送中', value: '推送中' },
  { label: '已推送', value: '已推送' },
  { label: '转存成功', value: '转存成功' },
  { label: '待转存', value: '待转存' },
  { label: '最终失败', value: '最终失败' },
]

const columns = [
  { title: '名称', key: 'name', minWidth: 220, ellipsis: { tooltip: true } },
  { title: '标签', key: 'tags', minWidth: 140, ellipsis: { tooltip: true } },
  {
    title: '源链接',
    key: 'original_link',
    minWidth: 280,
    ellipsis: { tooltip: true },
    render: (row: any) => renderLink(row.original_link),
  },
  {
    title: '我的分享链接',
    key: 'new_share_link',
    minWidth: 280,
    ellipsis: { tooltip: true },
    render: (row: any) => renderLink(row.new_share_link),
  },
]

function renderLink(link?: string) {
  if (!link) return '-'
  return h('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, link)
}

function searchResources() {
  page.value = 1
  loadData()
}

async function loadData() {
  loading.value = true
  try {
    const params: any = { page: page.value - 1, page_size: pageSize }
    if (search.value) params.search = search.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await api.get('/api/resources', { params })
    resources.value = res.data.items || []
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
