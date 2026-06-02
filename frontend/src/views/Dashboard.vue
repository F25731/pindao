<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button :loading="loading" @click="loadData">刷新</n-button>
    </n-space>

    <n-grid :cols="4" :x-gap="16" :y-gap="16">
      <n-gi v-for="item in statCards" :key="item.label">
        <n-card size="small">
          <n-statistic :label="item.label" :value="item.value" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-card title="近7天处理趋势" style="margin-top: 24px;">
      <div v-if="dailyStats.length" style="display: flex; align-items: flex-end; gap: 8px; height: 120px;">
        <div v-for="day in dailyStats" :key="day.date" style="flex: 1; text-align: center;">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
            <div
              :style="{ height: Math.max(4, day.transferred * 4) + 'px', width: '20px', background: '#18a058', borderRadius: '2px' }"
            ></div>
            <span style="font-size: 11px; color: #666;">{{ day.date }}</span>
            <span style="font-size: 11px;">{{ day.transferred }}</span>
          </div>
        </div>
      </div>
      <n-empty v-else description="暂无数据" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { NButton, NGrid, NGi, NCard, NStatistic, NEmpty, NSpace } from 'naive-ui'
import { api } from '../api/client'

const overview = ref<Record<string, number>>({})
const dailyStats = ref<Array<{ date: string; transferred: number; pushed: number }>>([])
const loading = ref(false)

const statCards = computed(() => [
  { label: '总资源数', value: overview.value['总资源数'] || 0 },
  { label: '待转存', value: overview.value['待转存'] || 0 },
  { label: '转存成功', value: overview.value['转存成功'] || 0 },
  { label: '已推送', value: overview.value['已推送'] || 0 },
  { label: '待推送', value: overview.value['待推送'] || 0 },
  { label: '推送队列', value: overview.value['推送队列'] || 0 },
  { label: '失败待重试', value: overview.value['失败待重试'] || 0 },
  { label: '最终失败', value: overview.value['最终失败'] || 0 },
  { label: '今日处理', value: overview.value['今日处理'] || 0 },
  { label: '可用账号', value: overview.value['可用账号'] || 0 },
  { label: '总账号数', value: overview.value['总账号数'] || 0 },
  { label: '精确重复已跳过', value: overview.value['精确重复已跳过'] || 0 },
])

async function loadData() {
  loading.value = true
  try {
    const [overviewRes, dailyRes] = await Promise.all([
      api.get('/api/stats/overview'),
      api.get('/api/stats/daily'),
    ])
    overview.value = overviewRes.data
    dailyStats.value = dailyRes.data
  } catch (e) {
    console.error('加载统计失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
