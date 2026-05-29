<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button type="primary" @click="showAdd = true">添加账号</n-button>
    </n-space>

    <n-data-table :columns="columns" :data="accounts" :loading="loading" :pagination="false" :row-key="(r: any) => r.id" />

    <n-modal v-model:show="showAdd" preset="dialog" title="添加光鸭账号" positive-text="确认" negative-text="取消" @positive-click="handleAdd">
      <n-form :model="addForm">
        <n-form-item label="名称/备注">
          <n-input v-model:value="addForm.name" placeholder="如：账号1" />
        </n-form-item>
        <n-form-item label="Access Token">
          <n-input v-model:value="addForm.access_token" type="textarea" :rows="2" placeholder="登录后获取的 access_token" />
        </n-form-item>
        <n-form-item label="Refresh Token">
          <n-input v-model:value="addForm.refresh_token" type="textarea" :rows="2" placeholder="登录后获取的 refresh_token" />
        </n-form-item>
        <n-form-item label="Device ID (可选)">
          <n-input v-model:value="addForm.device_id" placeholder="留空自动生成" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-input-number v-model:value="addForm.priority" :min="0" :max="100" />
        </n-form-item>
      </n-form>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, reactive } from 'vue'
import { NDataTable, NSpace, NButton, NModal, NForm, NFormItem, NInput, NInputNumber, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const accounts = ref<any[]>([])
const loading = ref(false)
const showAdd = ref(false)

const addForm = reactive({
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

const columns = [
  { title: 'ID', key: 'id', width: 50 },
  { title: '名称', key: 'name', width: 120 },
  {
    title: '状态', key: 'status', width: 100,
    render: (row: any) => h(NTag, { type: (statusColorMap[row.status] || 'default') as any, size: 'small' }, () => row.status)
  },
  { title: '优先级', key: 'priority', width: 70 },
  { title: '已处理', key: 'processed_count', width: 70 },
  { title: '错误次数', key: 'error_count', width: 80 },
  { title: '最近错误', key: 'last_error', width: 150, ellipsis: { tooltip: true } },
  { title: '最近使用', key: 'last_used_at', width: 160, render: (row: any) => row.last_used_at?.slice(0, 19).replace('T', ' ') || '-' },
  {
    title: '操作', key: 'actions', width: 120,
    render: (row: any) => h(NSpace, {}, () => [
      h(NButton, { size: 'small', type: 'error', onClick: () => deleteAccount(row.id) }, () => '删除'),
    ])
  },
]

async function handleAdd() {
  if (!addForm.name || !addForm.access_token || !addForm.refresh_token) {
    message.error('请填写必要信息')
    return false
  }
  try {
    await api.post('/api/accounts', addForm)
    message.success('添加成功')
    showAdd.value = false
    addForm.name = ''
    addForm.access_token = ''
    addForm.refresh_token = ''
    addForm.device_id = ''
    addForm.priority = 0
    loadData()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '添加失败')
  }
}

async function deleteAccount(id: number) {
  try {
    await api.delete(`/api/accounts/${id}`)
    message.success('已删除')
    loadData()
  } catch (e: any) {
    message.error('删除失败')
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
