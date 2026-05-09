<template>
  <div>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-input-number v-model="topK" :min="1" :max="10" label="推荐数量" />
      </el-col>
      <el-col :span="8">
        <el-slider v-model="alpha" :min="0" :max="1" :step="0.1" show-input />
        <span>语义权重 alpha</span>
      </el-col>
      <el-col :span="8">
        <el-slider v-model="beta" :min="0" :max="1" :step="0.1" show-input />
        <span>尺寸权重 beta</span>
      </el-col>
    </el-row>
    <el-button type="primary" @click="searchSimilar" :loading="loading">查找相似图纸</el-button>
    <el-table v-if="similarResults.length" :data="similarResults" style="margin-top: 20px">
      <el-table-column prop="part_name" label="零件名称" />
      <el-table-column prop="drawing_number" label="图号" />
      <el-table-column prop="material" label="材料" />
      <el-table-column prop="score" label="相似度">
        <template #default="{ row }">{{ (row.score * 100).toFixed(2) }}%</template>
      </el-table-column>
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button link type="primary" @click="loadDrawing(row.conv_uuid)">加载</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider />
    <h3>关键词语义搜索</h3>
    <el-input v-model="keyword" placeholder="输入关键词，如：铝合金支架" style="width: 70%" />
    <el-input-number v-model="kwTopK" :min="1" :max="20" style="margin-left: 12px" />
    <el-button @click="semanticSearch" type="primary" style="margin-left: 12px">搜索</el-button>
    <el-table v-if="searchResults.length" :data="searchResults" style="margin-top: 20px">
      <el-table-column prop="part_name" label="零件名称" />
      <el-table-column prop="drawing_number" label="图号" />
      <el-table-column prop="score" label="相似度">
        <template #default="{ row }">{{ (row.score * 100).toFixed(2) }}%</template>
      </el-table-column>
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button link type="primary" @click="loadDrawing(row.conv_uuid)">加载</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { getSimilarDrawings, semanticSearch as apiSearch } from '@/api/knowledge'
import { useDrawingStore } from '@/stores/drawing'
import { ElMessage } from 'element-plus'

const store = useDrawingStore()
const topK = ref(5)
const alpha = ref(0.7)
const beta = ref(0.3)
const loading = ref(false)
const similarResults = ref([])
const keyword = ref('')
const kwTopK = ref(5)
const searchResults = ref([])

const searchSimilar = async () => {
  if (!store.currentInfo) {
    ElMessage.warning('请先解析图纸')
    return
  }
  loading.value = true
  const res = await getSimilarDrawings(store.currentDrawing.convUuid, topK.value, alpha.value, beta.value)
  similarResults.value = res || []
  loading.value = false
}

const semanticSearch = async () => {
  if (!keyword.value.trim()) {
    ElMessage.warning('请输入关键词')
    return
  }
  loading.value = true
  const res = await apiSearch(keyword.value, kwTopK.value)
  searchResults.value = res || []
  loading.value = false
}

const loadDrawing = async (convUuid) => {
  await store.loadHistoryDrawing(convUuid, '')
  // 刷新界面由父组件控制，通过路由或全局状态重新渲染
  window.location.reload() // 简易刷新，可改用路由跳转
}
</script>