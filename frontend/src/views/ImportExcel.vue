<template>
  <div>
    <n-space style="margin-bottom: 16px;">
      <n-button @click="importResult = null">刷新</n-button>
    </n-space>

    <n-card title="导入资源文件">
      <n-alert type="info" style="margin-bottom: 16px;">
        支持 .xlsx 和 .csv 格式。百万级数据建议使用 CSV（速度快 10 倍以上）。表格需包含三列：名称、标签、链接。
      </n-alert>
      <n-upload
        :action="'/api/imports/upload'"
        :headers="uploadHeaders"
        accept=".xlsx,.xls,.csv"
        :max="1"
        @finish="handleUploadFinish"
        @error="handleUploadError"
      >
        <n-upload-dragger>
          <div style="padding: 24px; text-align: center;">
            <p style="font-size: 16px; margin-bottom: 8px;">点击或拖拽文件到此处</p>
            <p style="color: #999;">支持 .xlsx / .csv，大文件推荐 CSV</p>
          </div>
        </n-upload-dragger>
      </n-upload>
    </n-card>

    <n-card v-if="importResult" title="导入结果" style="margin-top: 16px;">
      <n-descriptions bordered :column="2">
        <n-descriptions-item label="批次 ID">{{ importResult.batch_id }}</n-descriptions-item>
        <n-descriptions-item label="状态">{{ importResult.status }}</n-descriptions-item>
        <n-descriptions-item label="提示">{{ importResult.message }}</n-descriptions-item>
      </n-descriptions>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NButton, NCard, NUpload, NUploadDragger, NDescriptions, NDescriptionsItem, NSpace, useMessage } from 'naive-ui'

const message = useMessage()
const importResult = ref<any>(null)

const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
}))

function handleUploadFinish({ event }: any) {
  try {
    const res = JSON.parse(event.target.response)
    importResult.value = res
    message.success(`已加入后台导入队列：批次 #${res.batch_id}`)
  } catch {
    message.error('解析导入结果失败')
  }
}

function handleUploadError() {
  message.error('上传失败，请检查文件格式')
}
</script>
