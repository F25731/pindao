<template>
  <div>
    <n-card title="导出 Excel">
      <n-form inline>
        <n-form-item label="按批次">
          <n-input-number v-model:value="batchId" placeholder="批次ID" clearable style="width: 140px;" />
        </n-form-item>
        <n-form-item label="按状态">
          <n-select v-model:value="status" :options="statusOptions" clearable placeholder="选择状态" style="width: 160px;" />
        </n-form-item>
        <n-form-item>
          <n-button type="primary" :loading="exporting" @click="doExport">生成 Excel</n-button>
        </n-form-item>
      </n-form>
    </n-card>

    <n-card v-if="exportResult" title="导出结果" style="margin-top: 16px;">
      <p>已导出 {{ exportResult.count }} 条资源</p>
      <n-button type="primary" @click="download">下载文件</n-button>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NForm, NFormItem, NInputNumber, NSelect, NButton, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const batchId = ref<number | null>(null)
const status = ref<string | null>(null)
const exporting = ref(false)
const exportResult = ref<any>(null)

const statusOptions = [
  { label: '转存成功', value: '转存成功' },
  { label: '待推送', value: '待推送' },
  { label: '已推送', value: '已推送' },
  { label: '待转存', value: '待转存' },
  { label: '最终失败', value: '最终失败' },
]

async function doExport() {
  exporting.value = true
  try {
    const params: any = {}
    if (batchId.value) params.batch_id = batchId.value
    if (status.value) params.status = status.value
    const res = await api.post('/api/export/excel', null, { params })
    exportResult.value = res.data
    message.success(`已生成，共 ${res.data.count} 条`)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

function download() {
  if (!exportResult.value?.filename) return
  const token = localStorage.getItem('token')
  window.open(`/api/export/download/${exportResult.value.filename}?token=${token}`, '_blank')
}
</script>
