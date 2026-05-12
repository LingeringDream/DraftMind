<template>
  <el-container class="home-container">
    <el-aside width="260px" class="aside">
      <DrawingSidebar @upload="showUploadDialog = true" />
    </el-aside>
    <el-main>
      <TaskProgress />

      <!-- 未上传任何图纸时显示上传区域 -->
      <div v-if="!store.currentDrawing">
        <el-upload
          drag
          multiple
          accept=".pdf,.jpg,.jpeg,.png,.dxf,.dwg"
          :auto-upload="false"
          :on-change="handleFilesChange"
          :file-list="fileList"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽或点击上传图纸（PDF/图片/CAD）</div>
        </el-upload>
        <el-switch v-model="uploadToOss" active-text="上传到云端 OSS" inactive-text="本地存储"
                   style="margin-top: 12px" />
        <el-button v-if="fileList.length" @click="uploadAndParse" type="primary" style="margin-top: 12px">
          上传并解析
        </el-button>
      </div>

      <!-- 已上传图纸：解析前先展示预览图，解析后展示完整信息 -->
      <div v-else>
        <!-- 图纸预览（上传后立即显示，不等解析完成） -->
        <div v-if="previewImages.length" class="preview-section">
          <h3 class="preview-title">{{ store.currentDrawing?.name || '图纸预览' }}</h3>
          <div class="preview-grid">
            <el-image
              v-for="(img, idx) in previewImages"
              :key="idx"
              :src="img.src"
              fit="contain"
              class="preview-img"
              :preview-src-list="previewImages.map(i => i.src)"
              :initial-index="idx"
            />
          </div>
        </div>

        <!-- 解析完成后展示完整标签页 -->
        <el-tabs v-if="store.currentInfo" v-model="activeTab" style="margin-top: 16px">
          <el-tab-pane label="图纸信息" name="info">
            <DrawingInfo />
          </el-tab-pane>
          <el-tab-pane label="智能审图" name="review">
            <ReviewPanel />
          </el-tab-pane>
          <el-tab-pane label="相似推荐" name="similar">
            <SimilarPanel />
          </el-tab-pane>
          <el-tab-pane label="图纸问答" name="chat">
            <ChatPanel />
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-main>
  </el-container>

  <!-- 上传对话框 -->
  <el-dialog v-model="showUploadDialog" title="上传图纸" width="40%">
    <!-- [CAD] accept 新增 .dxf/.dwg，提示文字更新为 PDF/图片/CAD -->
    <el-upload
      drag
      multiple
      accept=".pdf,.jpg,.jpeg,.png,.dxf,.dwg"
      :on-change="handleFilesChange"
      :auto-upload="false"
      :file-list="fileList"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖拽或点击选择文件（PDF/图片/CAD）</div>
    </el-upload>
    <!-- [OSS] 云端存储开关，对话框内同步显示 -->
    <el-switch v-model="uploadToOss" active-text="上传到云端 OSS" inactive-text="本地存储"
               style="margin-top: 12px" />
    <template #footer>
      <el-button @click="showUploadDialog = false">取消</el-button>
      <el-button type="primary" @click="uploadAndParse">上传并解析</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDrawingStore } from '@/stores/drawing'
import DrawingSidebar from '@/components/DrawingSidebar.vue'
import TaskProgress from '@/components/TaskProgress.vue'
import DrawingInfo from '@/components/DrawingInfo.vue'
import ReviewPanel from '@/components/ReviewPanel.vue'
import SimilarPanel from '@/components/SimilarPanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { pdfToImages, loadImageFromFile } from '@/utils/image'

const store = useDrawingStore()
const showUploadDialog = ref(false)
const fileList = ref([])
const uploadToOss = ref(false)  // [OSS] 是否上传到云端 OSS，默认关闭（本地存储）

// 当前图纸的预览图片（上传后立即可用，解析完成前也能展示）
const previewImages = computed(() => store.currentDrawing?.images || [])

// 上传组件文件变化时收集文件
const handleFilesChange = (file, files) => {
  fileList.value = files
}

// 上传并解析
const uploadAndParse = async () => {
  if (fileList.value.length === 0) {
    ElMessage.warning('请先选择文件')
    return
  }
  for (const fileItem of fileList.value) {
    const file = fileItem.raw
    let images = null
    try {
      // [CAD] CAD 文件跳过客户端图片渲染，直接将原始字节交给后端转换
      const isCad = /\.(dxf|dwg)$/i.test(file.name)
      if (isCad) {
        images = []  // [CAD] 空数组，后端 run_parse_job 会自动识别并转换
      } else if (file.type === 'application/pdf') {
        const buffer = await file.arrayBuffer()
        images = await pdfToImages(new Uint8Array(buffer))
      } else {
        const img = await loadImageFromFile(file)
        images = [img]
      }
      store.addDrawing({
        name: file.name,
        fileBytes: await file.arrayBuffer(),
        fileType: file.type,
      }, images)
    } catch (err) {
      ElMessage.error(`处理文件 ${file.name} 失败: ${err.message}`)
      continue
    }
  }
  // 并行提交所有图纸的解析任务
  const allKeys = Object.keys(store.drawings)
  const submitResults = await Promise.all(
    allKeys.map((key, idx) => store.submitParseJob(key, idx, uploadToOss.value))
  )
  const successCount = submitResults.filter(Boolean).length
  if (successCount > 0) {
    ElMessage.success(`已提交 ${successCount} 个解析任务，请查看进度`)
  } else {
    ElMessage.error('所有任务提交失败')
  }
  showUploadDialog.value = false
  fileList.value = []
}

const activeTab = ref('info')
</script>

<style>
.home-container {
  height: 100vh;
  overflow: hidden;
}
.home-container > .el-aside {
  overflow: hidden;
}
.home-container > .el-main {
  overflow: hidden;
}
.aside {
  background-color: #f5f7fa;
  border-right: 1px solid #e4e7ed;
}

.preview-section {
  margin-bottom: 16px;
}

.preview-title {
  font-size: 15px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 12px;
}

.preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.preview-img {
  width: 100%;
  max-height: 500px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
}
</style>