<template>
  <el-container class="home-container">
    <el-aside width="260px" class="aside">
      <DrawingSidebar @upload="showUploadDialog = true" />
    </el-aside>
    <el-main>
      <TaskProgress />
      
      <!-- 未解析任何图纸时显示上传区域 -->
      <div v-if="!store.currentInfo && !Object.keys(store.jobs).length">
        <!-- [CAD] accept 新增 .dxf/.dwg，提示文字更新为 PDF/图片/CAD -->
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
        <!-- [OSS] 云端存储开关，默认关闭（图片存储在本地） -->
        <el-switch v-model="uploadToOss" active-text="上传到云端 OSS" inactive-text="本地存储"
                   style="margin-top: 12px" />
        <el-button v-if="fileList.length" @click="uploadAndParse" type="primary" style="margin-top: 12px">
          上传并解析
        </el-button>
      </div>

      <div v-else-if="store.currentInfo">
        <el-tabs v-model="activeTab">
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
import { ref } from 'vue'            // 只需导入 ref，不再需要 computed
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
  // 解析第一个上传的图纸
  const firstKey = Object.keys(store.drawings)[0]
  if (firstKey) {
    await store.submitParseJob(firstKey, 0, uploadToOss.value)  // [OSS] 传递存储选项
    ElMessage.success('已提交解析任务，请稍后查看进度')
  }
  showUploadDialog.value = false
  fileList.value = []
}

const activeTab = ref('info')
</script>

<style>
.home-container {
  height: 100vh;
}
.aside {
  background-color: #f5f7fa;
  border-right: 1px solid #e4e7ed;
}
</style>