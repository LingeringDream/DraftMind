<template>
  <div>
    <el-input
      type="textarea"
      :rows="4"
      placeholder="企业自定义审核规则（可选）\n示例：\n- 禁止使用 Q235 材料\n- 所有配合面粗糙度 Ra≤1.6"
      v-model="customRules"
    />
    <el-button type="primary" @click="startReview" :loading="loading" style="margin-top: 12px">
      开始审图
    </el-button>
    <div v-if="report" class="review-result">
      <el-alert :type="report.overall_pass ? 'success' : 'error'" :title="report.overall_pass ? '通过' : '未通过'" />
      <el-descriptions :column="3" border>
        <el-descriptions-item label="风险等级">{{ report.risk_level }}</el-descriptions-item>
        <el-descriptions-item label="ERROR">{{ errorCount }}</el-descriptions-item>
        <el-descriptions-item label="WARNING">{{ warningCount }}</el-descriptions-item>
      </el-descriptions>
      <p>{{ report.summary }}</p>
      <el-collapse>
        <el-collapse-item v-for="(issue, idx) in report.issues" :key="idx" :title="`${issue.severity}: ${issue.description.slice(0,60)}`">
          <p><strong>描述：</strong>{{ issue.description }}</p>
          <p><strong>建议：</strong>{{ issue.suggestion }}</p>
          <p v-if="issue.reference"><strong>标准：</strong>{{ issue.reference }}</p>
        </el-collapse-item>
      </el-collapse>
      <el-button @click="exportReport" type="info" plain>导出报告 (JSON)</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDrawingStore } from '@/stores/drawing'
import { ElMessage } from 'element-plus'

const store = useDrawingStore()
const customRules = ref('')
const loading = ref(false)
const report = computed(() => store.currentDrawing?.reviewReport)

const errorCount = computed(() => report.value?.issues?.filter(i => i.severity === 'ERROR').length || 0)
const warningCount = computed(() => report.value?.issues?.filter(i => i.severity === 'WARNING').length || 0)

const startReview = async () => {
  if (!store.currentInfo) {
    ElMessage.warning('请先解析图纸')
    return
  }
  loading.value = true
  await store.runReview(customRules.value)
  loading.value = false
}

const exportReport = () => {
  const data = JSON.stringify(report.value, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `review_${store.currentDrawing.convUuid.slice(0,8)}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.review-result {
  margin-top: 20px;
}
</style>