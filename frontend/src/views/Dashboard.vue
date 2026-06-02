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

    <n-card title="系统实时详情日志" style="margin-top: 24px;">
      <template #header-extra>
        <n-space align="center">
          <n-tag size="small" type="success">自动刷新</n-tag>
          <n-button size="small" :loading="logsLoading" @click="loadLogs">刷新日志</n-button>
        </n-space>
      </template>
      <div ref="logBox" class="log-console">
        <div v-for="log in systemLogs" :key="log.id" class="log-line">
          <span class="log-time">{{ formatTime(log.created_at) }}</span>
          <span :class="['log-level', `log-${log.level}`]">{{ log.level.toUpperCase() }}</span>
          <span class="log-source">{{ log.source }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
        <n-empty v-if="!systemLogs.length" description="暂无日志" />
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick, onUnmounted, watch } from 'vue'
import { NButton, NGrid, NGi, NCard, NStatistic, NEmpty, NSpace, NDataTable, NTag } from 'naive-ui'
import { api } from '../api/client'

const overview = ref<Record<string, number>>({})
const dailyStats = ref<Array<{ date: string; transferred: number; pushed: number }>>([])
const systemLogs = ref<any[]>([])
const loading = ref(false)
const logsLoading = ref(false)
const logBox = ref<HTMLElement | null>(null)
let logTimer: number | undefined

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

async function loadLogs() {
  logsLoading.value = true
  try {
    const res = await api.get('/api/stats/logs', { params: { limit: 160 } })
    systemLogs.value = res.data || []
  } finally {
    logsLoading.value = false
  }
}

function formatTime(value: string) {
  return value?.slice(5, 19).replace('T', ' ') || '-'
}

watch(systemLogs, async () => {
  await nextTick()
  if (logBox.value) {
    logBox.value.scrollTop = logBox.value.scrollHeight
  }
})

onMounted(() => {
  loadData()
  loadLogs()
  logTimer = window.setInterval(loadLogs, 3000)
})

onUnmounted(() => {
  if (logTimer) window.clearInterval(logTimer)
})
</script>

<style scoped>
.log-console {
  height: 320px;
  overflow-y: auto;
  padding: 12px;
  border-radius: 6px;
  background: #111827;
  color: #d1d5db;
  font-family: Consolas, Monaco, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.7;
}

.log-line {
  display: grid;
  grid-template-columns: 88px 64px 86px 1fr;
  gap: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.log-time {
  color: #9ca3af;
}

.log-level {
  font-weight: 700;
}

.log-info,
.log-success {
  color: #34d399;
}

.log-warning {
  color: #fbbf24;
}

.log-error {
  color: #f87171;
}

.log-source {
  color: #93c5fd;
}

.log-message {
  color: #e5e7eb;
}
</style>
