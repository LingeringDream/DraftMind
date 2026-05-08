import client from './client'

export const createDrawingTask = (formData) =>
  client.post('/conversation/new', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })

export const getDrawingInfo = (convUuid) =>
  client.get(`/conversation/${convUuid}/info`)

export const getReviewReport = (convUuid, customRules = '') =>
  client.post(`/conversation/${convUuid}/review`, { custom_rules: customRules })

export const askDrawingQuestion = (convUuid, question) =>
  client.post(`/conversation/${convUuid}/ask`, { question })

export const getConversationList = () => client.get('/conversation/list')