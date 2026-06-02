<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button :loading="loading" @click="loadData">刷新</n-button>
    </n-space>

    <n-card title="详细统计">
      <n-descriptions bordered :column="3">
        <n-descriptions-item v-for="(value, key) in overview" :key="key" :label="key">
          {{ value }}
        </n-descriptions-item>
      </n-descriptions>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NButton, NCard, NDescriptions, NDescriptionsItem, NSpace } from 'naive-ui'
import { api } from '../api/client'

const overview = ref<Record<string, number>>({})
const loading = ref(false)

async function loadData() {
  loading.value = true
  try {
    const res = await api.get('/api/stats/overview')
    overview.value = res.data
  } catch (e) {
    console.error('加载统计失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
