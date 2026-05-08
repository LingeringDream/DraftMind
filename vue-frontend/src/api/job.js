import client from './client'

export const getJobStatus = (jobId) => client.get(`/job/${jobId}/status`)

export const prioritizeJob = (jobId) =>
  client.post(`/job/${jobId}/prioritize`, { priority: 0 })