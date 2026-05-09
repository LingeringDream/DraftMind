<template>
  <div v-if="info" class="drawing-info">

    <!-- 零件名称 + 图号 -->
    <div class="part-header">
      <span class="part-name">{{ info.basic_info?.part_name || '未知零件' }}</span>
      <el-tag v-if="info.basic_info?.drawing_number" effect="dark" size="default">
        {{ info.basic_info.drawing_number }}
      </el-tag>
    </div>

    <!-- 基本信息：平铺卡片行 -->
    <div class="param-row">
      <div class="param-card card-blue">
        <div class="param-label">图号</div>
        <div class="param-value">{{ info.basic_info?.drawing_number || '—' }}</div>
      </div>
      <div class="param-card card-orange">
        <div class="param-label">材料</div>
        <div class="param-value">{{ info.basic_info?.material || '—' }}</div>
      </div>
      <div class="param-card card-green">
        <div class="param-label">表面处理</div>
        <div class="param-value">{{ info.basic_info?.surface_treatment || '—' }}</div>
      </div>
    </div>

    <!-- 主要尺寸：平铺大卡片 -->
    <div class="param-row">
      <div class="dim-card">
        <div class="dim-label">长度</div>
        <div class="dim-value">{{ info.dimensions?.length || 0 }}<span class="dim-unit">mm</span></div>
      </div>
      <div class="dim-card">
        <div class="dim-label">宽度</div>
        <div class="dim-value">{{ info.dimensions?.width || 0 }}<span class="dim-unit">mm</span></div>
      </div>
      <div class="dim-card">
        <div class="dim-label">高度 / 厚度</div>
        <div class="dim-value">{{ info.dimensions?.height_thickness || 0 }}<span class="dim-unit">mm</span></div>
      </div>
      <div v-if="info.dimensions?.other_dimensions" class="dim-card dim-card-wide">
        <div class="dim-label">其他尺寸</div>
        <div class="dim-value-sm">{{ info.dimensions.other_dimensions }}</div>
      </div>
    </div>

    <!-- 尺寸公差：平铺卡片 -->
    <div v-if="info.tolerances?.length" class="section">
      <div class="section-label">尺寸公差</div>
      <div class="param-row wrap">
        <div v-for="(tol, idx) in info.tolerances" :key="idx" class="tol-card">
          <div class="tol-name">{{ tol.feature }}</div>
          <div class="tol-size">φ {{ tol.nominal }}</div>
          <el-tag :type="tol.tolerance?.includes('-') ? 'danger' : 'success'" effect="dark" size="small">
            {{ tol.tolerance }}
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 形位公差：平铺卡片 -->
    <div v-if="info.geometric_tolerances?.length" class="section">
      <div class="section-label">形位公差</div>
      <div class="param-row wrap">
        <div v-for="(gt, idx) in info.geometric_tolerances" :key="idx" class="gt-card">
          <div class="gt-name">{{ gt.item }}</div>
          <div class="gt-value">{{ gt.value }}<span class="dim-unit">mm</span></div>
        </div>
      </div>
    </div>

    <!-- 表面粗糙度：平铺卡片 -->
    <div v-if="info.surface_roughness?.length" class="section">
      <div class="section-label">表面粗糙度</div>
      <div class="param-row wrap">
        <div v-for="(sr, idx) in info.surface_roughness" :key="idx" class="sr-card">
          <div class="sr-name">{{ sr.surface_location }}</div>
          <div class="sr-value">Ra {{ sr.value }}<span class="dim-unit">μm</span></div>
        </div>
      </div>
    </div>

    <!-- 技术要求：标签平铺 -->
    <div v-if="info.technical_requirements?.length" class="section">
      <div class="section-label">技术要求</div>
      <div class="req-tags">
        <el-tag v-for="(req, idx) in info.technical_requirements" :key="idx" size="default" effect="plain">
          {{ req }}
        </el-tag>
      </div>
    </div>

    <!-- 图纸预览 -->
    <div v-if="images && images.length" class="section">
      <div class="section-label">图纸预览</div>
      <div class="preview-grid">
        <el-image
          v-for="(img, idx) in images"
          :key="idx"
          :src="img.src"
          fit="contain"
          class="preview-img"
          :preview-src-list="images.map(i => i.src)"
          :initial-index="idx"
        />
      </div>
      <el-input
        v-for="(img, idx) in images"
        :key="'note-' + idx"
        type="textarea"
        :rows="2"
        :placeholder="`第 ${idx+1} 页批注`"
        :model-value="annotations[idx+1] || ''"
        @input="val => saveAnnotation(idx+1, val)"
        style="margin-top: 8px"
      />
    </div>
    <div v-else-if="!Object.keys(store.jobs || {}).length" class="no-preview">
      从历史记录加载的图纸不支持图像预览
    </div>
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

<style scoped>
.drawing-info {
  padding: 8px 0;
}

/* 零件标题 */
.part-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.part-name {
  font-size: 24px;
  font-weight: 800;
  color: #1a1a1a;
  border-left: 5px solid #409eff;
  padding-left: 14px;
}

/* 平铺卡片行 */
.param-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.param-row.wrap {
  flex-wrap: wrap;
}

/* 基本信息卡片 */
.param-card {
  flex: 1;
  padding: 14px 18px;
  border-radius: 10px;
  border: 1px solid;
}

.card-blue  { background: #ecf5ff; border-color: #b3d8ff; }
.card-orange { background: #fdf6ec; border-color: #f5dab1; }
.card-green  { background: #f0f9eb; border-color: #c2e7b0; }

.param-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 500;
}

.param-value {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  word-break: break-all;
}

/* 尺寸大卡片 */
.dim-card {
  flex: 1;
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f9ff 100%);
  border: 2px solid #b3d8ff;
  border-radius: 12px;
  padding: 16px 20px;
  text-align: center;
}

.dim-card-wide {
  flex: 2;
}

.dim-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 500;
}

.dim-value {
  font-size: 28px;
  font-weight: 800;
  color: #409eff;
  line-height: 1.2;
}

.dim-value-sm {
  font-size: 14px;
  font-weight: 600;
  color: #606266;
  line-height: 1.5;
}

.dim-unit {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 2px;
}

/* 区块标题 */
.section {
  margin-bottom: 16px;
}

.section-label {
  font-size: 13px;
  font-weight: 700;
  color: #606266;
  margin-bottom: 10px;
  letter-spacing: 1px;
}

/* 公差卡片 */
.tol-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 140px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tol-name {
  font-size: 12px;
  color: #909399;
}

.tol-size {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
  font-family: monospace;
}

/* 形位公差卡片 */
.gt-card {
  background: #fef0f0;
  border: 1px solid #fbc4c4;
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 100px;
  text-align: center;
}

.gt-name {
  font-size: 12px;
  color: #f56c6c;
  font-weight: 600;
  margin-bottom: 4px;
}

.gt-value {
  font-size: 20px;
  font-weight: 800;
  color: #f56c6c;
}

/* 粗糙度卡片 */
.sr-card {
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 120px;
  text-align: center;
}

.sr-name {
  font-size: 12px;
  color: #e6a23c;
  font-weight: 600;
  margin-bottom: 4px;
}

.sr-value {
  font-size: 18px;
  font-weight: 800;
  color: #e6a23c;
}

/* 技术要求标签 */
.req-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 图纸预览 */
.preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.preview-img {
  width: 100%;
  max-height: 400px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
}

.no-preview {
  color: #c0c4cc;
  font-size: 13px;
  text-align: center;
  padding: 20px;
}
</style>
