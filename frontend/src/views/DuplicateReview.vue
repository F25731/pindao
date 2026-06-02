<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button :loading="loading" @click="loadData">刷新</n-button>
      <n-tag type="warning">待审核: {{ stats.pending || 0 }}</n-tag>
      <n-tag type="success">已处理: {{ stats.resolved || 0 }}</n-tag>
      <n-button type="primary" :disabled="!selectedIds.length" @click="batchDecide('skip')">批量跳过</n-button>
      <n-button :disabled="!selectedIds.length" @click="batchDecide('use_new')">批量使用当前</n-button>
      <n-button :disabled="!selectedIds.length" @click="batchDecide('keep_both')">批量都保留</n-button>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="reviews"
      :loading="loading"
      :pagination="false"
      :row-key="(r: any) => r.id"
      @update:checked-row-keys="handleCheck"
    />

    <n-modal v-model:show="showDetail" preset="card" title="疑似重复对比" style="width: 800px;">
      <n-grid :cols="2" :x-gap="16" v-if="detailData">
        <n-gi>
          <n-card title="已有资源" size="small">
            <p><strong>名称:</strong> {{ detailData.existing_resource.name }}</p>
            <p><strong>标签:</strong> {{ detailData.existing_resource.tags }}</p>
            <p><strong>链接:</strong> {{ detailData.existing_resource.original_link }}</p>
            <p><strong>状态:</strong> {{ detailData.existing_resource.status }}</p>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card title="当前导入资源" size="small">
            <p><strong>名称:</strong> {{ detailData.new_resource.name }}</p>
            <p><strong>标签:</strong> {{ detailData.new_resource.tags }}</p>
            <p><strong>链接:</strong> {{ detailData.new_resource.original_link }}</p>
            <p><strong>相似度:</strong> {{ (detailData.similarity_score * 100).toFixed(0) }}%</p>
            <p><strong>原因:</strong> {{ detailData.match_reason }}</p>
          </n-card>
        </n-gi>
      </n-grid>
      <n-space style="margin-top: 16px;" justify="end">
        <n-button @click="decide('use_existing')">保留已有</n-button>
        <n-button @click="decide('use_new')">使用当前</n-button>
        <n-button type="primary" @click="decide('keep_both')">都保留</n-button>
        <n-button type="error" @click="decide('skip')">跳过当前</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NDataTable, NSpace, NTag, NButton, NModal, NGrid, NGi, NCard, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const reviews = ref<any[]>([])
const loading = ref(false)
const stats = ref<Record<string, number>>({})
const selectedIds = ref<number[]>([])
const showDetail = ref(false)
const detailData = ref<any>(null)
const currentReviewId = ref<number | null>(null)

function resourceCell(nameKey: string, idKey: string, statusKey: string, tagsKey: string) {
  return (row: any) => h('div', { class: 'resource-cell' }, [
    h('div', { class: 'resource-title' }, row[nameKey] || `资源 #${row[idKey]}`),
    h('div', { class: 'resource-meta' }, [
      `#${row[idKey]}`,
      row[statusKey] ? ` · ${row[statusKey]}` : '',
      row[tagsKey] ? ` · ${row[tagsKey]}` : '',
    ]),
  ])
}

const columns = [
  { type: 'selection' as const },
  { title: 'ID', key: 'id', width: 60 },
  {
    title: '当前导入资源',
    key: 'new_name',
    minWidth: 220,
    ellipsis: { tooltip: true },
    render: resourceCell('new_name', 'new_resource_id', 'new_status', 'new_tags'),
  },
  {
    title: '数据库已有资源',
    key: 'existing_name',
    minWidth: 220,
    ellipsis: { tooltip: true },
    render: resourceCell('existing_name', 'existing_resource_id', 'existing_status', 'existing_tags'),
  },
  {
    title: '相似度', key: 'similarity_score', width: 80,
    render: (row: any) => `${(row.similarity_score * 100).toFixed(0)}%`
  },
  { title: '原因', key: 'match_reason', ellipsis: { tooltip: true } },
  { title: '创建时间', key: 'created_at', width: 160, render: (row: any) => row.created_at?.slice(0, 19).replace('T', ' ') },
  {
    title: '操作', key: 'actions', width: 80,
    render: (row: any) => h(NButton, { size: 'small', onClick: () => viewDetail(row.id) }, () => '查看')
  },
]

function handleCheck(keys: number[]) {
  selectedIds.value = keys
}

async function viewDetail(id: number) {
  try {
    const res = await api.get(`/api/duplicates/${id}`)
    detailData.value = res.data
    currentReviewId.value = id
    showDetail.value = true
  } catch (e: any) {
    message.error('加载详情失败')
  }
}

async function decide(decision: string) {
  if (!currentReviewId.value) return
  try {
    await api.post(`/api/duplicates/${currentReviewId.value}/decide`, { decision })
    message.success('已处理')
    showDetail.value = false
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '操作失败')
  }
}

async function batchDecide(decision: string) {
  if (!selectedIds.value.length) return
  try {
    await api.post('/api/duplicates/batch-decide', { ids: selectedIds.value, decision })
    message.success(`批量处理 ${selectedIds.value.length} 条`)
    selectedIds.value = []
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '批量操作失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const [reviewsRes, statsRes] = await Promise.all([
      api.get('/api/duplicates', { params: { status: 'pending' } }),
      api.get('/api/duplicates/stats'),
    ])
    reviews.value = reviewsRes.data
    stats.value = statsRes.data
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.resource-cell {
  min-width: 0;
  line-height: 1.45;
}

.resource-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-meta {
  color: #8c8c8c;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
