<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button type="primary" @click="showSmsLogin = true">手机号登录添加</n-button>
      <n-button @click="showTokenAdd = true">Token 直接添加</n-button>
      <n-button :loading="refreshingAll" @click="refreshAllAccounts">刷新全部容量</n-button>
    </n-space>

    <n-data-table :columns="columns" :data="accounts" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />

    <!-- 手机号登录弹窗 -->
    <n-modal v-model:show="showSmsLogin" preset="card" title="手机号验证码登录" style="width: 450px;">
      <n-steps :current="smsStep" size="small" style="margin-bottom: 16px;">
        <n-step title="输入手机号" />
        <n-step title="输入验证码" />
        <n-step title="完成" />
      </n-steps>

      <!-- Step 1: 输入手机号 -->
      <div v-if="smsStep === 1">
        <n-form-item label="手机号">
          <n-input v-model:value="smsForm.phone" placeholder="输入光鸭账号手机号" />
        </n-form-item>
        <n-form-item label="账号备注 (可选)">
          <n-input v-model:value="smsForm.accountName" placeholder="如：账号1" />
        </n-form-item>
        <n-button type="primary" :loading="smsLoading" block @click="smsInit">发送验证码</n-button>
      </div>

      <!-- Step 2: 输入验证码 -->
      <div v-if="smsStep === 2">
        <n-alert type="info" style="margin-bottom: 12px;">验证码已发送到 {{ smsForm.phone }}</n-alert>
        <n-form-item label="验证码">
          <n-input v-model:value="smsForm.code" placeholder="输入短信验证码" @keyup.enter="smsVerifyAndSignin" />
        </n-form-item>
        <n-button type="primary" :loading="smsLoading" block @click="smsVerifyAndSignin">验证并登录</n-button>
      </div>

      <!-- Step 3: 完成 -->
      <div v-if="smsStep === 3">
        <n-result status="success" title="登录成功" :description="`账号已添加到账号池`" />
      </div>
    </n-modal>

    <!-- Token 直接添加弹窗 -->
    <n-modal v-model:show="showTokenAdd" preset="dialog" title="直接添加光鸭账号" positive-text="确认" negative-text="取消" @positive-click="handleTokenAdd">
      <n-form :model="tokenForm">
        <n-form-item label="名称/备注">
          <n-input v-model:value="tokenForm.name" placeholder="如：账号1" />
        </n-form-item>
        <n-form-item label="Access Token">
          <n-input v-model:value="tokenForm.access_token" type="textarea" :rows="2" placeholder="登录后获取的 access_token" />
        </n-form-item>
        <n-form-item label="Refresh Token">
          <n-input v-model:value="tokenForm.refresh_token" type="textarea" :rows="2" placeholder="登录后获取的 refresh_token" />
        </n-form-item>
        <n-form-item label="Device ID (可选)">
          <n-input v-model:value="tokenForm.device_id" placeholder="留空自动生成" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-input-number v-model:value="tokenForm.priority" :min="0" :max="100" />
        </n-form-item>
      </n-form>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, reactive } from 'vue'
import {
  NDataTable, NSpace, NButton, NModal, NForm, NFormItem, NInput, NInputNumber,
  NTag, NSteps, NStep, NAlert, NResult, NProgress, useMessage
} from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const accounts = ref<any[]>([])
const loading = ref(false)
const showSmsLogin = ref(false)
const showTokenAdd = ref(false)
const refreshingAll = ref(false)

// SMS 登录状态
const smsStep = ref(1)
const smsLoading = ref(false)
const smsForm = reactive({
  phone: '',
  accountName: '',
  code: '',
  sessionKey: '',
})

// Token 直接添加
const tokenForm = reactive({
  name: '',
  access_token: '',
  refresh_token: '',
  device_id: '',
  priority: 0,
})

const statusColorMap: Record<string, string> = {
  available: 'success',
  full: 'warning',
  expired: 'error',
  rate_limited: 'warning',
  disabled: 'error',
}

function formatBytes(value?: number | null) {
  if (!value) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = Number(value)
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function usagePercent(row: any) {
  if (!row.total_capacity_bytes || !row.used_capacity_bytes) return 0
  return Math.min(100, Math.round((row.used_capacity_bytes / row.total_capacity_bytes) * 100))
}

function capacityStatus(row: any) {
  const percent = usagePercent(row)
  if (row.status === 'full' || percent >= 95) return 'error'
  if (percent >= 80) return 'warning'
  return 'success'
}

function renderCapacity(row: any) {
  if (!row.total_capacity_bytes && !row.used_capacity_bytes) {
    return h('div', { style: 'font-size: 12px; color: #8c8c8c;' }, [
      h('div', '容量未知'),
      h('div', { style: 'margin-top: 2px;' }, '转存时会按光鸭返回自动识别满盘'),
    ])
  }
  return h('div', { style: 'min-width: 180px;' }, [
    h(NProgress, {
      type: 'line',
      percentage: usagePercent(row),
      status: capacityStatus(row) as any,
      indicatorPlacement: 'inside',
      height: 18,
      processing: row.status === 'available' && usagePercent(row) >= 80,
    }),
    h('div', { style: 'margin-top: 4px; font-size: 12px; color: #666;' }, `${formatBytes(row.used_capacity_bytes)} / ${formatBytes(row.total_capacity_bytes)}`),
  ])
}

const columns = [
  { title: 'ID', key: 'id', width: 50 },
  { title: '名称', key: 'name', width: 120 },
  {
    title: '状态', key: 'status', width: 100,
    render: (row: any) => h(NTag, { type: (statusColorMap[row.status] || 'default') as any, size: 'small' }, () => row.status)
  },
  { title: '优先级', key: 'priority', width: 70 },
  {
    title: '容量', key: 'capacity', width: 220,
    render: renderCapacity
  },
  { title: '已处理', key: 'processed_count', width: 70 },
  { title: '错误次数', key: 'error_count', width: 80 },
  { title: '最近错误', key: 'last_error', width: 150, ellipsis: { tooltip: true } },
  { title: '最近使用', key: 'last_used_at', width: 160, render: (row: any) => row.last_used_at?.slice(0, 19).replace('T', ' ') || '-' },
  {
    title: '操作', key: 'actions', width: 220,
    render: (row: any) => h(NSpace, {}, () => [
      h(NButton, { size: 'small', onClick: () => refreshAccount(row.id) }, () => '刷新容量'),
      row.status !== 'available'
        ? h(NButton, { size: 'small', type: 'primary', onClick: () => enableAccount(row.id) }, () => '启用')
        : null,
      h(NButton, { size: 'small', type: 'error', onClick: () => deleteAccount(row.id) }, () => '删除'),
    ].filter(Boolean))
  },
]

// ===== SMS 登录流程 =====

async function smsInit() {
  if (!smsForm.phone) {
    message.error('请输入手机号')
    return
  }
  smsLoading.value = true
  try {
    // Step 1: init
    const initRes = await api.post('/api/accounts/login/sms/init', { phone: smsForm.phone })
    smsForm.sessionKey = initRes.data.session_key

    // Step 2: send
    await api.post('/api/accounts/login/sms/send', {
      phone: smsForm.phone,
      session_key: smsForm.sessionKey,
    })

    message.success('验证码已发送')
    smsStep.value = 2
  } catch (e: any) {
    message.error(e.response?.data?.detail || '发送验证码失败')
  } finally {
    smsLoading.value = false
  }
}

async function smsVerifyAndSignin() {
  if (!smsForm.code) {
    message.error('请输入验证码')
    return
  }
  smsLoading.value = true
  try {
    // Step 3: verify
    await api.post('/api/accounts/login/sms/verify', {
      session_key: smsForm.sessionKey,
      code: smsForm.code,
    })

    // Step 4: signin
    await api.post('/api/accounts/login/sms/signin', {
      session_key: smsForm.sessionKey,
      code: smsForm.code,
      account_name: smsForm.accountName || smsForm.phone,
    })

    message.success('登录成功，账号已添加')
    smsStep.value = 3
    loadData()

    // 3秒后关闭弹窗
    setTimeout(() => {
      showSmsLogin.value = false
      smsStep.value = 1
      smsForm.phone = ''
      smsForm.code = ''
      smsForm.accountName = ''
      smsForm.sessionKey = ''
    }, 2000)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '验证失败')
  } finally {
    smsLoading.value = false
  }
}

// ===== Token 直接添加 =====

async function handleTokenAdd() {
  if (!tokenForm.name || !tokenForm.access_token || !tokenForm.refresh_token) {
    message.error('请填写必要信息')
    return false
  }
  try {
    await api.post('/api/accounts', tokenForm)
    message.success('添加成功')
    showTokenAdd.value = false
    tokenForm.name = ''
    tokenForm.access_token = ''
    tokenForm.refresh_token = ''
    tokenForm.device_id = ''
    tokenForm.priority = 0
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '添加失败')
  }
}

async function deleteAccount(id: number) {
  if (!window.confirm('删除未使用账号会直接移除；已被任务或资源引用的账号会改为停用归档。确定继续？')) return
  try {
    const res = await api.delete(`/api/accounts/${id}`)
    message.success(res.data.message || (res.data.archived ? '账号已停用归档' : '已删除'))
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '删除失败')
  }
}

async function refreshAccount(id: number) {
  try {
    await api.post(`/api/accounts/${id}/refresh`)
    message.success('容量已刷新')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '刷新失败')
  }
}

async function refreshAllAccounts() {
  refreshingAll.value = true
  try {
    const res = await api.post('/api/accounts/refresh-all')
    message.success(`刷新完成：成功 ${res.data.refreshed || 0} 个，失败 ${res.data.failed || 0} 个`)
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '刷新失败')
  } finally {
    refreshingAll.value = false
  }
}

async function enableAccount(id: number) {
  try {
    await api.post(`/api/accounts/${id}/enable`)
    message.success('账号已启用')
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '启用失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.get('/api/accounts')
    accounts.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
