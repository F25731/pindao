<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button :loading="loading" @click="loadData">刷新</n-button>
    </n-space>

    <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
      <n-gi v-for="item in statCards" :key="item.label">
        <n-card size="small">
          <n-statistic :label="item.label" :value="item.value" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" style="margin-top: 24px;">
      <n-gi>
        <n-card title="资源状态">
          <n-data-table :columns="statusColumns" :data="resourceRows" :pagination="false" size="small" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card title="任务队列">
          <n-data-table :columns="statusColumns" :data="taskRows" :pagination="false" size="small" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-card title="近7天处理趋势" style="margin-top: 24px;">
      <div v-if="dailyStats.length" style="display: flex; align-items: flex-end; gap: 8px; height: 120px;">
        <div v-for="day in dailyStats" :key="day.date" style="flex: 1; text-align: center;">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
            <div
              :style="{ height: barHeight(day.transferred) + 'px', width: '20px', background: '#18a058', borderRadius: '2px' }"
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
import { NButton, NGrid, NGi, NCard, NStatistic, NEmpty, NSpace, NDataTable } from 'naive-ui'
import { api } from '../api/client'

const overview = ref<Record<string, number>>({})
const dailyStats = ref<Array<{ date: string; transferred: number; pushed: number }>>([])
const loading = ref(false)

const statCards = computed(() => [
  { label: '总资源数', value: overview.value['总资源数'] || 0 },
  { label: '待转存', value: overview.value['待转存'] || 0 },
  { label: '转存成功', value: overview.value['转存成功'] || 0 },
  { label: '待推送', value: overview.value['待推送'] || 0 },
  { label: '已推送', value: overview.value['已推送'] || 0 },
  { label: '待处理任务', value: overview.value['任务_pending'] || 0 },
  { label: '运行中任务', value: overview.value['任务_running'] || 0 },
  { label: '失败任务', value: overview.value['转存失败任务'] || 0 },
  { label: '推送队列', value: overview.value['推送队列'] || 0 },
  { label: '今日处理', value: overview.value['今日处理'] || 0 },
  { label: '可用账号', value: overview.value['可用账号'] || 0 },
  { label: '总账号数', value: overview.value['总账号数'] || 0 },
])

const statusColumns = [
  { title: '状态', key: 'label' },
  { title: '数量', key: 'value', width: 90 },
]

const resourceRows = computed(() => [
  { label: '待转存', value: overview.value['待转存'] || 0 },
  { label: '转存中', value: overview.value['转存中'] || 0 },
  { label: '转存暂停', value: overview.value['转存暂停'] || 0 },
  { label: '转存成功', value: overview.value['转存成功'] || 0 },
  { label: '待推送', value: overview.value['待推送'] || 0 },
  { label: '已推送', value: overview.value['已推送'] || 0 },
  { label: '失败待重试', value: overview.value['失败待重试'] || 0 },
  { label: '最终失败', value: overview.value['最终失败'] || 0 },
  { label: '精确重复已跳过', value: overview.value['精确重复已跳过'] || 0 },
])

const taskRows = computed(() => [
  { label: '待处理 pending', value: overview.value['任务_pending'] || 0 },
  { label: '运行中 running', value: overview.value['任务_running'] || 0 },
  { label: '已暂停 paused', value: overview.value['任务_paused'] || 0 },
  { label: '可重试失败 failed_retryable', value: overview.value['任务_failed_retryable'] || 0 },
  { label: '最终失败 failed_final', value: overview.value['任务_failed_final'] || 0 },
  { label: '已成功 success', value: overview.value['任务_success'] || 0 },
  { label: '已跳过 skipped', value: overview.value['任务_skipped'] || 0 },
])

const maxTransferred = computed(() => Math.max(1, ...dailyStats.value.map((day) => day.transferred || 0)))

function barHeight(value: number) {
  return Math.max(4, Math.round((value / maxTransferred.value) * 90))
}

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
