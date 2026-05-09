<template>
  <el-card class="progress-card" v-if="Object.keys(jobs).length">
    <template #header>
      <span>后台解析任务进度</span>
      <el-switch v-model="autoRefresh" active-text="自动刷新" style="float: right" />
    </template>
    <div v-for="(jobId, key) in jobs" :key="key" class="job-item">
      <div class="job-title">{{ drawings[key]?.name || key.slice(0,8) }}</div>
      <el-progress
        :percentage="progressMap[key]?.percent || 0"
        :status="progressMap[key]?.status"
        :format="() => progressMap[key]?.text || '等待中'"
      />
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useDrawingStore } from '@/stores/drawing'
import { getJobStatus } from '@/api/job'

const store = useDrawingStore()
const jobs = computed(() => store.jobs)
const drawings = computed(() => store.drawings)
const autoRefresh = ref(true)
const progressMap = ref({})

let interval = null

const updateProgress = async () => {
  for (const [key, jobId] of Object.entries(jobs.value)) {
    const status = await getJobStatus(jobId)
    if (status) {
      const pct = status.progress_pct ? Math.round(status.progress_pct * 100) : 0
      let text = status.progress || '处理中'
      let statusType = ''
      if (status.status === 'done') {
        statusType = 'success'
        text = '解析完成'
        await store.pollJob(key)
      } else if (status.status === 'failed') {
        statusType = 'exception'
        text = '解析失败'
      } else {
        statusType = ''
      }
      progressMap.value[key] = { percent: pct, text, status: statusType }
    }
  }
}

watch(autoRefresh, (val) => {
  if (val && !interval) {
    interval = setInterval(updateProgress, 3000)
  } else if (!val && interval) {
    clearInterval(interval)
    interval = null
  }
})

onMounted(() => {
  if (autoRefresh.value) {
    interval = setInterval(updateProgress, 3000)
  }
  updateProgress()
})
onUnmounted(() => {
  if (interval) clearInterval(interval)
})
</script>

<style scoped>
.progress-card {
  margin-bottom: 16px;
}
.job-item {
  margin-bottom: 12px;
}
.job-title {
  font-size: 14px;
  font-weight: bold;
  margin-bottom: 6px;
}
</style>