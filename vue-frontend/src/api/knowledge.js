import client from './client'

// 相似图纸推荐
export const getSimilarDrawings = (convUuid, topK = 5, alpha = 0.7, beta = 0.3) =>
  client.get(`/knowledge/similar/${convUuid}`, {
    params: { top_k: topK, alpha, beta },
  })

// 语义搜索（关键词搜索）
export const semanticSearch = (keyword, topK = 5) =>
  client.post('/knowledge/search', { keyword, top_k: topK })