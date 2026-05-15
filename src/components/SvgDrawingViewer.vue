<template>
  <div class="svg-viewer-container">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="layers">
        <el-checkbox v-model="layers.basic" @change="refreshLayers">基本信息</el-checkbox>
        <el-checkbox v-model="layers.dimensions" @change="refreshLayers">尺寸</el-checkbox>
        <el-checkbox v-model="layers.tolerances" @change="refreshLayers">公差</el-checkbox>
        <el-checkbox v-model="layers.gdt" @change="refreshLayers">形位公差</el-checkbox>
        <el-checkbox v-model="layers.roughness" @change="refreshLayers">粗糙度</el-checkbox>
      </div>
      <div class="stats">
        <span>📊 标注统计：</span>
        <span>尺寸 {{ stats.dimensions }}</span>
        <span>公差 {{ stats.tolerances }}</span>
        <span>形位公差 {{ stats.gdt }}</span>
        <span>粗糙度 {{ stats.roughness }}</span>
        <span>基本信息 {{ stats.basic }}</span>
      </div>
      <el-button size="small" @click="resetView">重置视图</el-button>
    </div>

    <!-- SVG 交互区域 -->
    <div class="svg-wrapper" ref="svgWrapper" @wheel="onWheel" @mousedown="startPan" @mousemove="onPan" @mouseup="endPan">
      <svg
        ref="svgCanvas"
        :viewBox="viewBox"
        width="100%"
        height="100%"
        style="background-color: #f0f0f0;"
      >
        <!-- 底图（位图） -->
        <image
          v-if="imageUrl"
          :href="imageUrl"
          :width="imageWidth"
          :height="imageHeight"
          style="pointer-events: none;"
        />

        <!-- 基本信息图层 -->
        <g v-show="layers.basic" class="layer-basic">
          <template v-for="anno in annotations.basic" :key="anno.id">
            <circle :cx="anno.x" :cy="anno.y" r="5" fill="blue" cursor="pointer" @click="showDetail(anno)" />
            <text :x="anno.x + 8" :y="anno.y - 5" font-size="12" fill="blue">{{ anno.text }}</text>
          </template>
        </g>

        <!-- 尺寸图层 -->
        <g v-show="layers.dimensions" class="layer-dimensions">
          <template v-for="anno in annotations.dimensions" :key="anno.id">
            <line :x1="anno.startX" :y1="anno.startY" :x2="anno.endX" :y2="anno.endY" stroke="green" stroke-width="2" />
            <text :x="(anno.startX + anno.endX)/2" :y="(anno.startY + anno.endY)/2 - 5" font-size="12" fill="green" cursor="pointer" @click="showDetail(anno)">
              {{ anno.text }}
            </text>
          </template>
        </g>

        <!-- 公差图层 -->
        <g v-show="layers.tolerances" class="layer-tolerances">
          <template v-for="anno in annotations.tolerances" :key="anno.id">
            <rect :x="anno.x-20" :y="anno.y-10" width="40" height="18" fill="orange" fill-opacity="0.3" rx="3" />
            <text :x="anno.x" :y="anno.y+4" font-size="12" fill="orange" text-anchor="middle" cursor="pointer" @click="showDetail(anno)">
              {{ anno.text }}
            </text>
          </template>
        </g>

        <!-- 形位公差图层 -->
        <g v-show="layers.gdt" class="layer-gdt">
          <template v-for="anno in annotations.gdt" :key="anno.id">
            <polygon points="0,-8 8,0 0,8 -8,0" :transform="`translate(${anno.x},${anno.y})`" fill="red" cursor="pointer" @click="showDetail(anno)" />
            <text :x="anno.x + 12" :y="anno.y + 4" font-size="12" fill="red">{{ anno.text }}</text>
          </template>
        </g>

        <!-- 粗糙度图层 -->
        <g v-show="layers.roughness" class="layer-roughness">
          <template v-for="anno in annotations.roughness" :key="anno.id">
            <path d="M0,0 L8,-6 L16,0 L24,-6" stroke="purple" fill="none" stroke-width="1.5" :transform="`translate(${anno.x},${anno.y})`" />
            <text :x="anno.x + 28" :y="anno.y + 2" font-size="12" fill="purple" cursor="pointer" @click="showDetail(anno)">
              {{ anno.text }}
            </text>
          </template>
        </g>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'

const props = defineProps({
  imageUrl: { type: String, required: true },        // 底图URL
  imageWidth: { type: Number, required: true },      // 底图原始宽度
  imageHeight: { type: Number, required: true },     // 底图原始高度
  annotationsData: { type: Object, required: true }  // 标注数据 { basic, dimensions, tolerances, gdt, roughness }
})

// 图层开关
const layers = ref({
  basic: true,
  dimensions: true,
  tolerances: true,
  gdt: true,
  roughness: true
})

// 标注统计
const stats = ref({
  basic: 0,
  dimensions: 0,
  tolerances: 0,
  gdt: 0,
  roughness: 0
})

// 存储标注对象便于刷新统计
const annotations = ref({
  basic: [],
  dimensions: [],
  tolerances: [],
  gdt: [],
  roughness: []
})

// 视图控制
const viewBox = ref('0 0 1000 800')
const svgWrapper = ref(null)
const svgCanvas = ref(null)

let panning = false
let panStart = { x: 0, y: 0 }
let viewBoxStart = { x: 0, y: 0 }

// 刷新图层显示和统计
const refreshLayers = () => {
  computeStats()
}

// 计算当前显示的标注数量
const computeStats = () => {
  stats.value.basic = annotations.value.basic.length
  stats.value.dimensions = annotations.value.dimensions.length
  stats.value.tolerances = annotations.value.tolerances.length
  stats.value.gdt = annotations.value.gdt.length
  stats.value.roughness = annotations.value.roughness.length
}

// 点击标注详情
const showDetail = (anno) => {
  ElMessageBox.alert(
    `<strong>类型：</strong> ${anno.type}<br/>
     <strong>内容：</strong> ${anno.text}<br/>
     <strong>详细信息：</strong> ${anno.detail || '无'}`,
    '标注详情',
    { dangerouslyUseHTMLString: true }
  )
}

// 重置视图（显示完整图纸）
const resetView = () => {
  viewBox.value = `0 0 ${props.imageWidth} ${props.imageHeight}`
}

// 鼠标滚轮缩放（以鼠标位置为中心）
const onWheel = (e) => {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 1.1 : 0.9
  const [x, y, w, h] = viewBox.value.split(' ').map(Number)
  const rect = svgWrapper.value.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top
  const scaleX = w / rect.width
  const scaleY = h / rect.height
  const newW = w * delta
  const newH = h * delta
  if (newW < 100 || newH < 100) return
  const offsetX = (mouseX - x) * (newW / w) - (mouseX - x)
  const offsetY = (mouseY - y) * (newH / h) - (mouseY - y)
  viewBox.value = `${x - offsetX} ${y - offsetY} ${newW} ${newH}`
}

// 鼠标拖拽平移
const startPan = (e) => {
  if (e.button !== 0) return
  panning = true
  panStart = { x: e.clientX, y: e.clientY }
  const [x, y] = viewBox.value.split(' ').map(Number)
  viewBoxStart = { x, y }
}

const onPan = (e) => {
  if (!panning) return
  const dx = e.clientX - panStart.x
  const dy = e.clientY - panStart.y
  const [x, y, w, h] = viewBox.value.split(' ').map(Number)
  viewBox.value = `${viewBoxStart.x - dx} ${viewBoxStart.y - dy} ${w} ${h}`
}

const endPan = () => {
  panning = false
}

// 监听外部传入的标注数据并初始化
watch(() => props.annotationsData, (data) => {
  if (data) {
    annotations.value = {
      basic: data.basic || [],
      dimensions: data.dimensions || [],
      tolerances: data.tolerances || [],
      gdt: data.gdt || [],
      roughness: data.roughness || []
    }
    computeStats()
  }
}, { immediate: true, deep: true })

onMounted(() => {
  resetView()
})
</script>

<style scoped>
.svg-viewer-container {
  width: 100%;
  height: 600px;
  display: flex;
  flex-direction: column;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: white;
}
.toolbar {
  padding: 8px 12px;
  background: #f5f7fa;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e4e7ed;
  flex-wrap: wrap;
  gap: 8px;
}
.layers {
  display: flex;
  gap: 16px;
  align-items: center;
}
.stats {
  font-size: 13px;
  color: #606266;
}
.stats span {
  margin-right: 12px;
}
.svg-wrapper {
  flex: 1;
  position: relative;
  overflow: hidden;
  cursor: grab;
}
.svg-wrapper:active {
  cursor: grabbing;
}
svg {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
