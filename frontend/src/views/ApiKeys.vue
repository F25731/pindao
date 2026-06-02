<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button type="primary" @click="showCreate = true">创建 API 密钥</n-button>
    </n-space>

    <n-card title="API 调用说明" size="small" style="margin-bottom: 16px;">
      <n-alert type="info" style="margin-bottom: 12px;">
        外部程序通过 X-API-Key 调用接口。AstrBot 插件推荐使用 lease 领取任务，发送成功后 callback 回写结果。
      </n-alert>
      <n-code :code="apiGuide" language="bash" word-wrap />
    </n-card>

    <n-data-table :columns="columns" :data="keys" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />

    <n-modal v-model:show="showCreate" preset="dialog" title="创建 API 密钥" positive-text="创建" negative-text="取消" @positive-click="handleCreate">
      <n-form-item label="名称/用途">
        <n-input v-model:value="createName" placeholder="如：AstrBot 推送" />
      </n-form-item>
    </n-modal>

    <n-modal v-model:show="showKey" preset="dialog" title="密钥已创建" :closable="false">
      <n-alert type="warning" style="margin-bottom: 12px;">请立即复制保存，关闭后无法再次查看完整密钥</n-alert>
      <n-input :value="newKey" readonly type="textarea" :rows="2" />
      <template #action>
        <n-button type="primary" @click="copyKey">复制并关闭</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NAlert, NButton, NCard, NCode, NDataTable, NFormItem, NInput, NModal, NSpace, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const keys = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const showKey = ref(false)
const createName = ref('')
const newKey = ref('')
const apiGuide = `# 健康检查
curl -H "X-API-Key: 你的密钥" http://你的后端地址:8000/api/external/push/health

# 领取待推送资源，系统会把资源锁定为推送中，避免重复推送
curl -X POST -H "X-API-Key: 你的密钥" "http://你的后端地址:8000/api/external/push/lease?limit=10"

# 回调推送成功
curl -X POST -H "X-API-Key: 你的密钥" -H "Content-Type: application/json" \\
  -d '{"resource_id":1,"status":"success","message_id":"telegram-message-id"}' \\
  http://你的后端地址:8000/api/external/push/callback

# 回调推送失败
curl -X POST -H "X-API-Key: 你的密钥" -H "Content-Type: application/json" \\
  -d '{"resource_id":1,"status":"failed","error_message":"失败原因"}' \\
  http://你的后端地址:8000/api/external/push/callback`

const columns = [
  { title: 'ID', key: 'id', width: 50 },
  { title: '名称', key: 'name', width: 150 },
  { title: '前缀', key: 'key_prefix', width: 100 },
  {
    title: '状态', key: 'is_active', width: 80,
    render: (row: any) => h(NTag, { type: row.is_active ? 'success' : 'error', size: 'small' }, () => row.is_active ? '启用' : '禁用')
  },
  { title: '最近使用', key: 'last_used_at', width: 160, render: (row: any) => row.last_used_at?.slice(0, 19).replace('T', ' ') || '从未' },
  { title: '创建时间', key: 'created_at', width: 160, render: (row: any) => row.created_at?.slice(0, 19).replace('T', ' ') },
  {
    title: '操作', key: 'actions', width: 120,
    render: (row: any) => h(NSpace, {}, () => [
      h(NButton, { size: 'small', onClick: () => toggleKey(row) }, () => row.is_active ? '禁用' : '启用'),
      h(NButton, { size: 'small', type: 'error', onClick: () => deleteKey(row.id) }, () => '删除'),
    ])
  },
]

async function handleCreate() {
  if (!createName.value) {
    message.error('请输入名称')
    return false
  }
  try {
    const res = await api.post('/api/api-keys', { name: createName.value })
    newKey.value = res.data.key
    showKey.value = true
    createName.value = ''
    loadData()
  } catch (e: any) {
    message.error('创建失败')
  }
}

async function copyKey() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(newKey.value)
    } else {
      fallbackCopy(newKey.value)
    }
    message.success('已复制')
  } catch (e) {
    fallbackCopy(newKey.value)
    message.success('已复制')
  }
  showKey.value = false
  newKey.value = ''
}

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

async function toggleKey(row: any) {
  try {
    await api.put(`/api/api-keys/${row.id}`, null, { params: { is_active: !row.is_active } })
    message.success('已更新')
    loadData()
  } catch (e: any) {
    message.error('操作失败')
  }
}

async function deleteKey(id: number) {
  try {
    await api.delete(`/api/api-keys/${id}`)
    message.success('已删除')
    loadData()
  } catch (e: any) {
    message.error('删除失败')
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.get('/api/api-keys')
    keys.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
