<template>
  <div class="sidebar">
    <!-- Logo 区域 -->
    <div class="sidebar-logo">
      <img src="@/assets/logo.png" alt="DraftMind Logo" class="logo-img" />
      <span class="logo-text">DraftMind</span>
    </div>

    <!-- 当前会话图纸列表 -->
    <div v-if="Object.keys(drawings).length" class="section-title">当前图纸</div>
    <el-menu :default-active="currentKey" @select="handleSelect">
      <el-menu-item v-for="(drawing, key) in drawings" :key="key" :index="key">
        <span>{{ drawing.name || key.slice(0,8) }}</span>
        <el-badge v-if="jobs[key]" :value="'⏳'" type="warning" style="margin-left: 8px" />
      </el-menu-item>
    </el-menu>

    <el-divider />

    <!-- 历史图纸列表（从后端加载） -->
    <div class="section-title">历史图纸</div>
    <el-menu v-if="historyList.length" @select="handleHistorySelect">
      <el-menu-item v-for="item in historyList" :key="item.uuid" :index="item.uuid">
        <span>{{ item.title || item.uuid.slice(0,8) }}</span>
      </el-menu-item>
    </el-menu>
    <div v-else class="empty-hint">暂无历史记录</div>

    <el-divider />
    <el-button type="primary" @click="emit('upload')">上传新图纸</el-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDrawingStore } from '@/stores/drawing'
import { getConversationList } from '@/api/drawing'
import { ElMessage } from 'element-plus'

const store = useDrawingStore()
const drawings = computed(() => store.drawings)
const currentKey = computed(() => store.currentKey)
const jobs = computed(() => store.jobs)

const emit = defineEmits(['upload'])

// 历史图纸列表: [{uuid, title}, ...]
const historyList = ref([])

// 加载历史图纸列表
const fetchHistory = async () => {
  const data = await getConversationList()
  if (data) {
    historyList.value = Object.entries(data).map(([uuid, title]) => ({ uuid, title }))
  }
}

onMounted(fetchHistory)

const handleSelect = (key) => {
  store.switchDrawing(key)
  store.prioritizeCurrentJob()
}

// 点击历史图纸 → 加载到当前会话
const handleHistorySelect = async (uuid) => {
  // 如果已经加载过，直接切换
  if (store.drawings[uuid]) {
    store.switchDrawing(uuid)
    return
  }
  const ok = await store.loadHistoryDrawing(uuid, '')
  if (ok) {
    ElMessage.success('历史图纸加载成功')
  } else {
    ElMessage.error('加载失败')
  }
}
</script>

<style scoped>
.sidebar {
  padding: 16px;
  height: 100%;
  overflow-y: auto;
}

/* Logo 样式 */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid #e4e7ed;
}

.logo-img {
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.section-title {
  font-size: 12px;
  color: #909399;
  padding: 8px 8px 4px;
  font-weight: 500;
}

.empty-hint {
  font-size: 12px;
  color: #c0c4cc;
  padding: 8px;
  text-align: center;
}
</style>