import * as pdfjsLib from 'pdfjs-dist'

// 设置 worker 路径（确保 CDN 版本与包版本一致）
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'

export const pdfToImages = async (fileBytes, dpi = 150) => {
  const loadingTask = pdfjsLib.getDocument({ data: fileBytes })
  const pdf = await loadingTask.promise
  const images = []
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i)
    const viewport = page.getViewport({ scale: dpi / 72 })
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d')
    canvas.width = viewport.width
    canvas.height = viewport.height
    await page.render({ canvasContext: context, viewport }).promise
    const img = new Image()
    img.src = canvas.toDataURL('image/jpeg', 0.8)
    await new Promise((resolve) => { img.onload = resolve })
    images.push(img)
  }
  return images
}

export const imageToJpeg = (imgElement) => {
  return new Promise((resolve) => {
    const canvas = document.createElement('canvas')
    canvas.width = imgElement.width
    canvas.height = imgElement.height
    const ctx = canvas.getContext('2d')
    ctx.drawImage(imgElement, 0, 0)
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.8)
  })
}

export const loadImageFromFile = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = e.target.result
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}
