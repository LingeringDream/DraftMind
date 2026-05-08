<template>
  <div class="sidebar">
    <!-- 新增 Logo 区域 -->
    <div class="sidebar-logo">
      <img src="@/assets/logo.png" alt="DraftMind Logo" class="logo-img" />
      <span class="logo-text">DraftMind</span>
    </div>

    <el-menu :default-active="currentKey" @select="handleSelect">
      <el-menu-item v-for="(drawing, key) in drawings" :key="key" :index="key">
        <span>{{ drawing.name || key.slice(0,8) }}</span>
        <el-badge v-if="jobs[key]" :value="'⏳'" type="warning" style="margin-left: 8px" />
      </el-menu-item>
    </el-menu>
    <el-divider />
    <el-button type="primary" @click="emit('upload')">上传新图纸</el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useDrawingStore } from '@/stores/drawing'

const store = useDrawingStore()
const drawings = computed(() => store.drawings)
const currentKey = computed(() => store.currentKey)
const jobs = computed(() => store.jobs)

const emit = defineEmits(['upload'])

const handleSelect = (key) => {
  store.switchDrawing(key)
  store.prioritizeCurrentJob()
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
</style>