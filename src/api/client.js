import axios from 'axios'
import { ElMessage } from 'element-plus'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000'

const client = axios.create({
  baseURL,
  timeout: 60000,
})

client.interceptors.response.use(
  response => response.data,
  error => {
    const msg = error.response?.data?.error || error.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export const checkHealth = () => client.get('/')

export default client