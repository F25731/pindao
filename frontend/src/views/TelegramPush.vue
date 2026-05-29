<template>
  <div>
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
import { NGrid, NGi, NCard, NStatistic, NDataTable, NTag } from 'naive-ui'
import { api } from '../api/client'

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

onMounted(async () => {
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
})
</script>
