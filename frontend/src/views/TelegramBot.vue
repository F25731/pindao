<template>
  <div class="telegram-bot-page">
    <n-space style="margin-bottom: 16px;" align="center">
      <n-button :loading="loading" @click="loadAll">刷新</n-button>
      <n-button type="primary" :loading="checking" @click="checkHealth">检测接口</n-button>
      <n-tag :type="config.bot_running ? 'success' : 'default'">搜索 Bot: {{ config.bot_running ? '运行中' : '已停止' }}</n-tag>
      <n-tag :type="config.push_bot_running ? 'success' : 'default'">推送 Bot: {{ config.push_bot_running ? '运行中' : '已停止' }}</n-tag>
    </n-space>

    <n-grid :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
      <n-gi v-for="card in statCards" :key="card.label">
        <n-card size="small">
          <n-statistic :label="card.label" :value="card.value" />
          <div class="muted">{{ card.desc }}</div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-tabs type="line" animated>
      <n-tab-pane name="search" tab="搜索 Bot">
        <n-card size="small" title="搜索 Bot 配置">
          <n-space style="margin-bottom: 12px;">
            <n-button type="primary" :loading="actionLoading" @click="botAction('search', 'start')">启动</n-button>
            <n-button :loading="actionLoading" @click="botAction('search', 'restart')">重启</n-button>
            <n-button type="error" ghost :loading="actionLoading" @click="botAction('search', 'stop')">停止</n-button>
          </n-space>
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="12">
              <n-gi><n-form-item label="Telegram Bot Token"><n-input v-model:value="form.telegram_bot_token" type="password" placeholder="留空表示不修改" /></n-form-item></n-gi>
              <n-gi><n-form-item label="搜索 API Key"><n-input v-model:value="form.guangya_api_key" type="password" placeholder="需要 search:read 权限" /></n-form-item></n-gi>
              <n-gi><n-form-item label="pindao API 地址"><n-input v-model:value="form.guangya_api_base" placeholder="如 http://web:8000" /></n-form-item></n-gi>
              <n-gi><n-form-item label="状态过滤"><n-input v-model:value="form.status" placeholder="留空搜索全部" /></n-form-item></n-gi>
              <n-gi><n-form-item label="每页数量"><n-input-number v-model:value="form.page_size" :min="1" :max="50" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="最大展示数量"><n-input-number v-model:value="form.max_results" :min="0" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="请求超时(秒)"><n-input-number v-model:value="form.request_timeout_seconds" :min="3" :max="120" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="热门资源窗口(小时)"><n-input-number v-model:value="form.hot_window_hours" :min="1" :max="720" style="width: 100%;" /></n-form-item></n-gi>
            </n-grid>
            <n-space vertical>
              <n-checkbox v-model:checked="form.bot_enabled">启用搜索 Bot</n-checkbox>
              <n-checkbox v-model:checked="form.proxy_enabled">启用 Telegram 代理</n-checkbox>
            </n-space>
            <n-form-item label="代理地址" style="margin-top: 12px;"><n-input v-model:value="form.proxy_url" type="password" placeholder="留空不修改，支持 http:// 或 socks5://" /></n-form-item>
            <n-button type="primary" :loading="saving" @click="saveConfig">保存配置</n-button>
          </n-form>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="push" tab="推送 Bot">
        <n-card size="small" title="推送 Bot 配置">
          <n-space style="margin-bottom: 12px;">
            <n-button type="primary" :loading="actionLoading" @click="botAction('push', 'start')">启动</n-button>
            <n-button :loading="actionLoading" @click="botAction('push', 'restart')">重启</n-button>
            <n-button type="error" ghost :loading="actionLoading" @click="botAction('push', 'stop')">停止</n-button>
            <n-button type="warning" :loading="actionLoading" @click="pushOnce">手动推送一次</n-button>
          </n-space>
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="12">
              <n-gi><n-form-item label="推送 Bot Token"><n-input v-model:value="form.push_bot_token" type="password" placeholder="留空表示不修改" /></n-form-item></n-gi>
              <n-gi><n-form-item label="频道/群 ID"><n-input v-model:value="form.push_chat_id" placeholder="@channel 或 -100xxx" /></n-form-item></n-gi>
              <n-gi><n-form-item label="推送 API 地址"><n-input v-model:value="form.push_api_base" placeholder="如 http://web:8000" /></n-form-item></n-gi>
              <n-gi><n-form-item label="推送 API Key"><n-input v-model:value="form.push_api_key" type="password" placeholder="需要 push:read 和 push:callback 权限" /></n-form-item></n-gi>
              <n-gi><n-form-item label="轮询间隔(秒)"><n-input-number v-model:value="form.push_poll_interval" :min="5" :max="3600" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="每批数量"><n-input-number v-model:value="form.push_batch_size" :min="1" :max="100" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="发送间隔(秒)"><n-input-number v-model:value="form.push_send_interval" :min="0" :max="60" :step="0.5" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="领取超时恢复(分钟)"><n-input-number v-model:value="form.push_lease_stale_minutes" :min="5" :max="1440" style="width: 100%;" /></n-form-item></n-gi>
              <n-gi><n-form-item label="parse_mode"><n-select v-model:value="form.push_parse_mode" :options="parseModeOptions" /></n-form-item></n-gi>
            </n-grid>
            <n-space vertical>
              <n-checkbox v-model:checked="form.push_enabled">启用自动轮询推送</n-checkbox>
              <n-checkbox v-model:checked="form.push_proxy_enabled">推送 Bot 使用单独代理</n-checkbox>
            </n-space>
            <n-form-item label="推送代理地址" style="margin-top: 12px;"><n-input v-model:value="form.push_proxy_url" type="password" placeholder="留空不修改" /></n-form-item>
            <n-button type="primary" :loading="saving" @click="saveConfig">保存配置</n-button>
          </n-form>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="logs" tab="日志统计">
        <n-grid :cols="2" :x-gap="12" :y-gap="12">
          <n-gi>
            <n-card size="small" title="热门关键词">
              <n-empty v-if="!stats.keywords?.length" description="暂无数据" />
              <n-list v-else>
                <n-list-item v-for="item in stats.keywords" :key="item.keyword">
                  <n-space justify="space-between" style="width: 100%;"><span>{{ item.keyword }}</span><n-tag size="small">{{ item.count }}</n-tag></n-space>
                </n-list-item>
              </n-list>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" title="接口健康">
              <n-descriptions :column="1" size="small">
                <n-descriptions-item label="状态"><n-tag :type="health.guangya_api_ok ? 'success' : 'error'">{{ health.guangya_api_ok ? '正常' : '异常' }}</n-tag></n-descriptions-item>
                <n-descriptions-item label="延迟">{{ health.latency_ms ?? '-' }} ms</n-descriptions-item>
                <n-descriptions-item label="Key">{{ health.guangya_api?.key_name || '-' }}</n-descriptions-item>
                <n-descriptions-item label="错误">{{ health.guangya_api_error || '-' }}</n-descriptions-item>
              </n-descriptions>
            </n-card>
          </n-gi>
        </n-grid>
        <n-card size="small" title="实时日志" style="margin-top: 12px;">
          <n-space style="margin-bottom: 8px;"><n-button size="small" @click="loadLogs(true)">刷新日志</n-button></n-space>
          <n-empty v-if="!logs.length" description="暂无日志" />
          <n-timeline v-else>
            <n-timeline-item v-for="event in logs" :key="event.id" :type="logType(event.level)" :title="`${event.action} · ${event.level}`" :content="event.text" :time="formatTime(event.ts)" />
          </n-timeline>
        </n-card>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NCheckbox, NDescriptions, NDescriptionsItem, NEmpty, NForm, NFormItem,
  NGi, NGrid, NInput, NInputNumber, NList, NListItem, NSelect, NSpace, NStatistic,
  NTabPane, NTabs, NTag, NTimeline, NTimelineItem, useMessage
} from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const checking = ref(false)
const actionLoading = ref(false)
const config = ref<any>({})
const stats = ref<any>({ totals: {}, today: {}, keywords: [] })
const health = ref<any>({})
const logs = ref<any[]>([])
const lastEventId = ref(0)

const form = reactive<any>({
  telegram_bot_token: '', guangya_api_base: '', guangya_api_key: '', page_size: 10, max_results: 0,
  status: '', request_timeout_seconds: 20, bot_enabled: true, proxy_enabled: false, proxy_url: '', hot_window_hours: 48,
  push_bot_token: '', push_chat_id: '', push_enabled: false, push_api_base: '', push_api_key: '', push_proxy_enabled: false,
  push_proxy_url: '', push_poll_interval: 30, push_batch_size: 5, push_send_interval: 1, push_lease_stale_minutes: 30, push_parse_mode: '',
})

const parseModeOptions = [
  { label: '无', value: '' },
  { label: 'HTML', value: 'HTML' },
  { label: 'Markdown', value: 'Markdown' },
  { label: 'MarkdownV2', value: 'MarkdownV2' },
]

const statCards = computed(() => [
  { label: '今日搜索', value: stats.value.today?.searches || 0, desc: stats.value.today?.date || '' },
  { label: '今日推送', value: stats.value.today?.pushes || 0, desc: '推送成功数' },
  { label: '累计搜索', value: stats.value.totals?.searches || 0, desc: `详情 ${stats.value.totals?.details || 0}` },
  { label: '累计推送', value: stats.value.totals?.pushes || 0, desc: `失败 ${stats.value.totals?.push_errors || 0}` },
])

function applyConfig(data: any) {
  config.value = data || {}
  for (const key of Object.keys(form)) {
    if (key.includes('token') || key.includes('key') || key.includes('proxy_url')) {
      form[key] = ''
    } else if (data[key] !== undefined) {
      form[key] = data[key]
    }
  }
}

function payload() {
  const body: any = {}
  for (const key of Object.keys(form)) {
    const value = form[key]
    if ((key.includes('token') || key.includes('key') || key.includes('proxy_url')) && !value) continue
    body[key] = value
  }
  return body
}

async function loadConfig() {
  const res = await api.get('/api/telegram-bot/config')
  applyConfig(res.data)
}

async function loadStats() {
  const res = await api.get('/api/telegram-bot/stats')
  stats.value = res.data
  lastEventId.value = res.data.last_event_id || lastEventId.value
}

async function loadLogs(reset = false) {
  const res = await api.get('/api/telegram-bot/logs', { params: { after: reset ? 0 : lastEventId.value, limit: 200 } })
  logs.value = reset ? (res.data.events || []) : [...logs.value, ...(res.data.events || [])].slice(-200)
  lastEventId.value = res.data.last_event_id || lastEventId.value
}

async function checkHealth() {
  checking.value = true
  try {
    const res = await api.get('/api/telegram-bot/health')
    health.value = res.data
    message[res.data.guangya_api_ok ? 'success' : 'error'](res.data.guangya_api_ok ? '接口正常' : '接口异常')
  } finally {
    checking.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadStats(), loadLogs(true)])
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    const res = await api.put('/api/telegram-bot/config', payload())
    applyConfig(res.data)
    message.success('配置已保存')
  } finally {
    saving.value = false
  }
}

async function botAction(kind: 'search' | 'push', action: 'start' | 'stop' | 'restart') {
  actionLoading.value = true
  try {
    const res = await api.post(`/api/telegram-bot/${kind}/${action}`)
    message.success(res.data.message || '操作完成')
    await Promise.all([loadConfig(), loadStats()])
  } finally {
    actionLoading.value = false
  }
}

async function pushOnce() {
  actionLoading.value = true
  try {
    const res = await api.post('/api/telegram-bot/push/once')
    message.success(res.data.message || '推送完成')
    await Promise.all([loadStats(), loadLogs(true)])
  } finally {
    actionLoading.value = false
  }
}

function formatTime(value: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function logType(level: string) {
  if (level === 'success') return 'success'
  if (level === 'warn') return 'warning'
  if (level === 'error') return 'error'
  return 'info'
}

onMounted(loadAll)
</script>

<style scoped>
.telegram-bot-page { max-width: 1180px; }
.muted { color: #888; font-size: 12px; margin-top: 4px; }
</style>
