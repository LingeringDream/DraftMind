import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getDrawingInfo, getReviewReport, createDrawingTask, askDrawingQuestion } from '@/api/drawing'
import { getJobStatus, prioritizeJob } from '@/api/job'
import { imageToJpeg } from '@/utils/image'   // 移除未使用的 pdfToImages

// 辅助函数：根据图纸信息生成标注数据（移除未使用的 imageWidth/imageHeight 参数）
function generateAnnotationsFromInfo(info) {
  const annotations = {
    basic: [],
    dimensions: [],
    tolerances: [],
    gdt: [],
    roughness: []
  }

  if (!info) return annotations

  // 1. 基本信息
  annotations.basic.push({
    id: 'basic_1',
    type: '基本信息',
    text: `${info.basic_info?.part_name || '零件'} | 图号:${info.basic_info?.drawing_number || '-'} | 材料:${info.basic_info?.material || '-'}`,
    detail: `零件名称: ${info.basic_info?.part_name}\n图号: ${info.basic_info?.drawing_number}\n材料: ${info.basic_info?.material}\n表面处理: ${info.basic_info?.surface_treatment}`,
    x: 50,
    y: 30
  })

  // 2. 尺寸标注
  if (info.dimensions) {
    const dims = info.dimensions
    let idx = 1
    if (dims.length) {
      annotations.dimensions.push({
        id: `dim_${idx++}`,
        type: '尺寸',
        text: `长度 ${dims.length} mm`,
        detail: `标称长度: ${dims.length} mm`,
        startX: 150, startY: 120, endX: 350, endY: 120
      })
    }
    if (dims.width) {
      annotations.dimensions.push({
        id: `dim_${idx++}`,
        type: '尺寸',
        text: `宽度 ${dims.width} mm`,
        detail: `标称宽度: ${dims.width} mm`,
        startX: 400, startY: 200, endX: 600, endY: 200
      })
    }
    if (dims.height_thickness) {
      annotations.dimensions.push({
        id: `dim_${idx++}`,
        type: '尺寸',
        text: `厚度 ${dims.height_thickness} mm`,
        detail: `标称厚度: ${dims.height_thickness} mm`,
        startX: 500, startY: 300, endX: 500, endY: 400
      })
    }
  }

  // 3. 公差标注
  if (info.tolerances && info.tolerances.length) {
    info.tolerances.forEach((tol, i) => {
      annotations.tolerances.push({
        id: `tol_${i}`,
        type: '公差',
        text: `${tol.feature}: ${tol.nominal} ±${tol.tolerance}`,
        detail: `特征: ${tol.feature}\n名义尺寸: ${tol.nominal}\n公差范围: ${tol.tolerance}`,
        x: 150 + i * 120,
        y: 450
      })
    })
  } else {
    annotations.tolerances.push({
      id: 'tol_demo1',
      type: '公差',
      text: '直径 Φ50 ±0.1',
      detail: '轴径公差等级 IT7',
      x: 200, y: 480
    })
  }

  // 4. 形位公差
  annotations.gdt.push({
    id: 'gdt_1',
    type: '形位公差',
    text: '⊥0.05 A',
    detail: '垂直度 0.05 基准 A',
    x: 600, y: 100
  })
  annotations.gdt.push({
    id: 'gdt_2',
    type: '形位公差',
    text: '○0.02',
    detail: '圆度 0.02',
    x: 650, y: 150
  })

  // 5. 粗糙度
  annotations.roughness.push({
    id: 'rough_1',
    type: '粗糙度',
    text: 'Ra 1.6',
    detail: '表面粗糙度 Ra 1.6 μm',
    x: 300, y: 550
  })
  annotations.roughness.push({
    id: 'rough_2',
    type: '粗糙度',
    text: 'Ra 3.2',
    detail: '其余表面粗糙度 Ra 3.2 μm',
    x: 500, y: 580
  })

  return annotations
}

export const useDrawingStore = defineStore('drawing', () => {
  const drawings = ref({})
  const currentKey = ref(null)
  const jobs = ref({})
  const jobImages = ref({})

  const currentDrawing = computed(() => currentKey.value ? drawings.value[currentKey.value] : null)
  const currentInfo = computed(() => currentDrawing.value?.info || null)

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
      svgAnnotations: null,
      imageDimensions: null,
    }
    if (!currentKey.value) currentKey.value = key
  }

  const switchDrawing = (key) => {
    if (currentKey.value === key) return
    currentKey.value = key
  }

  const submitParseJob = async (key, priority = 0) => {
    const drawing = drawings.value[key]
    if (!drawing) return false

    const images = drawing.images
    if (!images || images.length === 0) {
      console.error(`图纸 ${key} 没有可用的图片数据`)
      return false
    }

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
        drawings.value[key].images = jobImages.value[key]
        // 获取图片尺寸
        let imgWidth = 800, imgHeight = 600
        if (jobImages.value[key] && jobImages.value[key][0]) {
          imgWidth = jobImages.value[key][0].width || 800
          imgHeight = jobImages.value[key][0].height || 600
        }
        drawings.value[key].svgAnnotations = generateAnnotationsFromInfo(info)  // 不再传递尺寸参数
        drawings.value[key].imageDimensions = { width: imgWidth, height: imgHeight }
      }
      delete jobs.value[key]
      delete jobImages.value[key]
    } else if (status === 'failed') {
      console.error(`Job ${jobId} failed:`, statusData.error)
      delete jobs.value[key]
      delete jobImages.value[key]
    }
  }

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
      images: null,
      fileBytes: null,
      svgAnnotations: generateAnnotationsFromInfo(info),  // 不再传递尺寸参数
      imageDimensions: { width: 800, height: 600 }
    }
    currentKey.value = key
    return true
  }

  const runReview = async (customRules = '') => {
    const drawing = currentDrawing.value
    if (!drawing || !drawing.convUuid) return null
    const report = await getReviewReport(drawing.convUuid, customRules)
    if (report) drawing.reviewReport = report
    return report
  }

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

  const clearChat = () => {
    if (currentDrawing.value) currentDrawing.value.chatHistory = []
  }

  const saveAnnotation = (pageNum, text) => {
    if (currentDrawing.value) {
      currentDrawing.value.annotations[pageNum] = text
    }
  }

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
