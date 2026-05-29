<template>
  <div>
    <n-data-table :columns="columns" :data="batches" :loading="loading" :pagination="false" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NDataTable, NTag } from 'naive-ui'
import { api } from '../api/client'

const batches = ref<any[]>([])
const loading = ref(false)

const columns = [
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
]

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.get('/api/imports/batches')
    batches.value = res.data
  } finally {
    loading.value = false
  }
})
</script>
