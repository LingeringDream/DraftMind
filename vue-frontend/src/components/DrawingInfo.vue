<template>
  <div v-if="info">
    <h2>{{ info.basic_info?.part_name || '未知零件' }}</h2>
    <el-descriptions :column="4" border>
      <el-descriptions-item label="图号">{{ info.basic_info?.drawing_number || '—' }}</el-descriptions-item>
      <el-descriptions-item label="材料">{{ info.basic_info?.material || '—' }}</el-descriptions-item>
      <el-descriptions-item label="表面处理">{{ info.basic_info?.surface_treatment || '—' }}</el-descriptions-item>
    </el-descriptions>
    <el-divider />
    <h3>主要尺寸</h3>
    <el-row :gutter="20">
      <el-col :span="8">长度: {{ info.dimensions?.length || 0 }} mm</el-col>
      <el-col :span="8">宽度: {{ info.dimensions?.width || 0 }} mm</el-col>
      <el-col :span="8">高度/厚度: {{ info.dimensions?.height_thickness || 0 }} mm</el-col>
    </el-row>
    <el-collapse v-if="info.tolerances?.length">
      <el-collapse-item title="尺寸公差">
        <el-table :data="info.tolerances" border size="small">
          <el-table-column prop="feature" label="特征" />
          <el-table-column prop="nominal" label="名义尺寸" />
          <el-table-column prop="tolerance" label="公差" />
        </el-table>
      </el-collapse-item>
    </el-collapse>
    <!-- 类似展示其他信息 -->
    <el-divider />
    <h3>图纸预览与批注</h3>
    <div v-if="images && images.length">
      <el-collapse v-for="(img, idx) in images" :key="idx">
        <el-collapse-item :title="`第 ${idx+1} 页`">
          <el-image :src="img.src" style="width:100%" />
          <el-input
            type="textarea"
            :rows="3"
            :placeholder="`第 ${idx+1} 页批注`"
            :model-value="annotations[idx+1] || ''"
            @input="val => saveAnnotation(idx+1, val)"
          />
        </el-collapse-item>
      </el-collapse>
    </div>
    <div v-else>从历史记录加载的图纸不支持图像预览</div>
  </div>
  <el-empty v-else description="暂无图纸信息" />
</template>

<script setup>
import { computed } from 'vue'
import { useDrawingStore } from '@/stores/drawing'

const store = useDrawingStore()
const info = computed(() => store.currentInfo)
const images = computed(() => store.currentDrawing?.images)
const annotations = computed(() => store.currentDrawing?.annotations || {})

const saveAnnotation = (page, text) => {
  store.saveAnnotation(page, text)
}
</script>