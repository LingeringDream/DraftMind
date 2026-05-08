import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getDrawingInfo, getReviewReport, createDrawingTask, askDrawingQuestion } from '@/api/drawing'
import { getJobStatus, prioritizeJob } from '@/api/job'
import { pdfToImages, imageToJpeg } from '@/utils/image'   // 工具函数见后

export const useDrawingStore = defineStore('drawing', () => {
  // 图纸库: key -> { file, images, convUuid, info, annotations, chatHistory, reviewReport }
  const drawings = ref({})
  const currentKey = ref(null)

  // 异步任务: key -> jobId
  const jobs = ref({})
  // 任务对应的预览图片
  const jobImages = ref({})

  const currentDrawing = computed(() => currentKey.value ? drawings.value[currentKey.value] : null)
  const currentInfo = computed(() => currentDrawing.value?.info || null)

  // 添加新图纸（上传后未解析）
  const addDrawing = (file, images) => {
    const key = file.name
    drawings.value[key] = {
      name: file.name,
      fileBytes: file.fileBytes,
      fileType: file.fileType,
      images,
      convUuid: null,
      info: null,
      annotations: {},
      chatHistory: [],
      reviewReport: null,
    }
    if (!currentKey.value) currentKey.value = key
  }

  // 切换图纸
  const switchDrawing = (key) => {
    if (currentKey.value === key) return
    currentKey.value = key
  }

  // 提交解析任务
  const submitParseJob = async (key, priority = 0) => {
    const drawing = drawings.value[key]
    if (!drawing) return false

    let images = drawing.images
    if (!images || images.length === 0) {
      // 如果图纸没有预处理的图片，现在处理（例如重新上传时）
      images = await preprocessFile(drawing.fileBytes, drawing.fileType)
      if (!images) return false
      drawing.images = images
    }

    // 构建 multipart form data
    const formData = new FormData()
    formData.append('priority', String(priority))
    const jpegPromises = images.map(async (img, idx) => {
      const blob = await imageToJpeg(img)
      return { idx, blob }
    })
    const jpegList = await Promise.all(jpegPromises)
    for (const { idx, blob } of jpegList) {
      formData.append('image', blob, `page_${idx+1}.jpg`)
    }

    const result = await createDrawingTask(formData)
    if (result && result.job_id) {
      jobs.value[key] = result.job_id
      jobImages.value[key] = images
      return true
    }
    return false
  }

  // 轮询任务状态并更新图纸数据（应在全局启动轮询）
  const pollJob = async (key) => {
    const jobId = jobs.value[key]
    if (!jobId) return
    const statusData = await getJobStatus(jobId)
    if (!statusData) return

    const status = statusData.status
    if (status === 'done') {
      const convUuid = statusData.conv_uuid
      const info = await getDrawingInfo(convUuid)
      if (info) {
        drawings.value[key].convUuid = convUuid
        drawings.value[key].info = info
        drawings.value[key].images = jobImages.value[key] // 保留预览图
      }
      delete jobs.value[key]
      delete jobImages.value[key]
    } else if (status === 'failed') {
      console.error(`Job ${jobId} failed:`, statusData.error)
      delete jobs.value[key]
      delete jobImages.value[key]
    }
  }

  // 加载历史图纸
  const loadHistoryDrawing = async (convUuid, title) => {
    const info = await getDrawingInfo(convUuid)
    if (!info) return false
    const key = convUuid
    drawings.value[key] = {
      name: title || info.basic_info?.part_name || convUuid.slice(0,8),
      convUuid,
      info,
      annotations: {},
      chatHistory: [],
      reviewReport: null,
      images: null, // 历史图纸不存图片数据
      fileBytes: null,
    }
    currentKey.value = key
    return true
  }

  // 审图
  const runReview = async (customRules = '') => {
    const drawing = currentDrawing.value
    if (!drawing || !drawing.convUuid) return null
    const report = await getReviewReport(drawing.convUuid, customRules)
    if (report) {
      drawing.reviewReport = report
    }
    return report
  }

  // 问答
  const askQuestion = async (question) => {
    const drawing = currentDrawing.value
    if (!drawing || !drawing.convUuid) return null
    const result = await askDrawingQuestion(drawing.convUuid, question)
    if (result?.answer) {
      drawing.chatHistory.push({ question, answer: result.answer })
      return result.answer
    }
    return null
  }

  // 清除聊天记录
  const clearChat = () => {
    if (currentDrawing.value) currentDrawing.value.chatHistory = []
  }

  // 保存批注
  const saveAnnotation = (pageNum, text) => {
    if (currentDrawing.value) {
      currentDrawing.value.annotations[pageNum] = text
    }
  }

  // 切换图纸时自动提升优先级
  const prioritizeCurrentJob = async () => {
    const key = currentKey.value
    if (key && jobs.value[key]) {
      await prioritizeJob(jobs.value[key])
    }
  }

  return {
    drawings,
    currentKey,
    jobs,
    jobImages,
    currentDrawing,
    currentInfo,
    addDrawing,
    switchDrawing,
    submitParseJob,
    pollJob,
    loadHistoryDrawing,
    runReview,
    askQuestion,
    clearChat,
    saveAnnotation,
    prioritizeCurrentJob,
  }
})