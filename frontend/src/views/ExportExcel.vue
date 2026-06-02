<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button @click="exportResult = null">刷新</n-button>
    </n-space>

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
      <n-button type="primary" :loading="downloading" @click="download">下载文件</n-button>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NCard, NForm, NFormItem, NInputNumber, NSelect, NSpace, useMessage } from 'naive-ui'
import { api } from '../api/client'

const message = useMessage()
const batchId = ref<number | null>(null)
const status = ref<string | null>(null)
const exporting = ref(false)
const downloading = ref(false)
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

async function download() {
  if (!exportResult.value?.filename) return
  downloading.value = true
  try {
    const res = await api.get(`/api/export/download/${exportResult.value.filename}`, {
      responseType: 'blob',
    })
    const blob = new Blob([res.data], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = exportResult.value.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '下载失败')
  } finally {
    downloading.value = false
  }
}
</script>
