<template>
  <div>
    <n-card title="导入 Excel">
      <n-upload
        :action="'/api/imports/upload'"
        :headers="uploadHeaders"
        accept=".xlsx,.xls"
        :max="1"
        @finish="handleUploadFinish"
        @error="handleUploadError"
      >
        <n-upload-dragger>
          <div style="padding: 24px; text-align: center;">
            <p style="font-size: 16px; margin-bottom: 8px;">点击或拖拽 Excel 文件到此处</p>
            <p style="color: #999;">支持 .xlsx 格式，表格需包含：名称、标签、链接 三列</p>
          </div>
        </n-upload-dragger>
      </n-upload>
    </n-card>

    <n-card v-if="importResult" title="导入结果" style="margin-top: 16px;">
      <n-descriptions bordered :column="2">
        <n-descriptions-item label="批次 ID">{{ importResult.batch_id }}</n-descriptions-item>
        <n-descriptions-item label="总行数">{{ importResult.total_rows }}</n-descriptions-item>
        <n-descriptions-item label="有效行数">{{ importResult.valid_rows }}</n-descriptions-item>
        <n-descriptions-item label="新增资源">{{ importResult.new_count }}</n-descriptions-item>
        <n-descriptions-item label="精确重复跳过">{{ importResult.duplicate_skipped }}</n-descriptions-item>
        <n-descriptions-item label="疑似重复">{{ importResult.fuzzy_flagged }}</n-descriptions-item>
        <n-descriptions-item label="解析失败">{{ importResult.parse_failed }}</n-descriptions-item>
      </n-descriptions>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NCard, NUpload, NUploadDragger, NDescriptions, NDescriptionsItem, useMessage } from 'naive-ui'

const message = useMessage()
const importResult = ref<any>(null)

const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
}))

function handleUploadFinish({ event }: any) {
  try {
    const res = JSON.parse(event.target.response)
    importResult.value = res
    message.success(`导入完成：新增 ${res.new_count} 条资源`)
  } catch {
    message.error('解析导入结果失败')
  }
}

function handleUploadError() {
  message.error('上传失败，请检查文件格式')
}
</script>
