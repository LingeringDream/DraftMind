<template>
  <div class="chat-container">
    <!-- 消息区域 -->
    <div class="chat-messages" ref="chatContainer">
      <!-- 空状态提示 -->
      <div v-if="!chatHistory.length && !loading" class="empty-hint">
        <div class="empty-icon"> </div>
        <div>基于当前图纸向 AI 提问，例如：</div>
        <div class="example-questions">
          <el-tag v-for="q in exampleQuestions" :key="q" effect="plain" class="example-tag"
                  @click="question = q">{{ q }}</el-tag>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-for="(msg, idx) in chatHistory" :key="idx" class="msg-pair">
        <!-- 用户消息：右侧气泡 -->
        <div class="msg-row msg-row-right">
          <div class="bubble bubble-user">
            <div class="bubble-text">{{ msg.question }}</div>
          </div>
          <div class="avatar avatar-user">你</div>
        </div>
        <!-- AI 消息：左侧气泡，支持 Markdown 渲染 -->
        <div class="msg-row msg-row-left">
          <div class="avatar avatar-ai">AI</div>
          <div class="bubble bubble-ai">
            <div class="bubble-text md-content" v-html="renderMarkdown(msg.answer)"></div>
          </div>
        </div>
      </div>

      <!-- 加载动画 -->
      <div v-if="loading" class="msg-row msg-row-left">
        <div class="avatar avatar-ai">AI</div>
        <div class="bubble bubble-ai">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input">
      <el-input
        v-model="question"
        type="textarea"
        :rows="2"
        placeholder="输入问题，Ctrl+Enter 发送"
        @keydown.ctrl.enter="sendQuestion"
        resize="none"
      />
      <div class="input-actions">
        <el-button v-if="chatHistory.length" @click="clearChat" text type="info" size="small">
          清除对话
        </el-button>
        <el-button type="primary" @click="sendQuestion" :loading="loading" :disabled="!question.trim()">
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useDrawingStore } from '@/stores/drawing'
import { ElMessage } from 'element-plus'

const store = useDrawingStore()
const chatHistory = computed(() => store.currentDrawing?.chatHistory || [])
const loading = ref(false)
const question = ref('')
const chatContainer = ref(null)

const exampleQuestions = [
  '这个零件的配合公差是多少？',
  '材料选择是否合理？',
  '有哪些技术要求需要注意？',
]

const sendQuestion = async () => {
  if (!question.value.trim()) return
  if (!store.currentInfo) {
    ElMessage.warning('请先解析图纸')
    return
  }
  loading.value = true
  const answer = await store.askQuestion(question.value)
  loading.value = false
  if (answer) {
    question.value = ''
    await nextTick()
    scrollToBottom()
  }
}

const clearChat = () => {
  store.clearChat()
}

const scrollToBottom = () => {
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

watch(chatHistory, () => {
  nextTick(scrollToBottom)
})

// --- 轻量 Markdown 渲染器（无外部依赖） ---
function renderMarkdown(text) {
  if (!text) return ''
  let html = text

  // 转义 HTML 特殊字符
  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  // 代码块 ```...```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre class="md-code-block"><code>${code.trim()}</code></pre>`
  })

  // 行内代码 `...`
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')

  // 标题 ### / ## / #
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')

  // 粗体 **...**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // 斜体 *...*
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')

  // 无序列表 - item
  html = html.replace(/^- (.+)$/gm, '<li class="md-li">$1</li>')
  html = html.replace(/(<li class="md-li">[\s\S]*?<\/li>)/g, '<ul class="md-ul">$1</ul>')
  // 合并相邻 ul
  html = html.replace(/<\/ul>\s*<ul class="md-ul">/g, '')

  // 有序列表 1. item
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="md-li">$1</li>')

  // 表格（简单支持）
  html = html.replace(/^\|(.+)\|$/gm, (match, content) => {
    const cells = content.split('|').map(c => c.trim())
    if (cells.every(c => /^[-:]+$/.test(c))) return '<!-- sep -->'
    const tag = 'td'
    const tds = cells.map(c => `<${tag}>${c}</${tag}>`).join('')
    return `<tr>${tds}</tr>`
  })
  html = html.replace(/((<tr>[\s\S]*?<\/tr>\s*)+)/g, '<table class="md-table">$1</table>')
  html = html.replace(/<!-- sep -->/g, '')

  // 换行
  html = html.replace(/\n/g, '<br>')

  // 清理多余 br
  html = html.replace(/<br>\s*(<h[234]|<pre|<ul|<table|<li)/g, '$1')
  html = html.replace(/(<\/h[234]|<\/pre>|<\/ul>|<\/table>|<\/li>)\s*<br>/g, '$1')

  return html
}
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 560px;
}

/* 消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

/* 空状态 */
.empty-hint {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 20px;
}

.empty-icon {
  font-size: 36px;
  margin-bottom: 8px;
}

.example-questions {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.example-tag {
  cursor: pointer;
}

/* 消息对 */
.msg-pair {
  margin-bottom: 20px;
}

.msg-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 6px;
}

.msg-row-right {
  flex-direction: row-reverse;
}

/* 头像 */
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.avatar-user {
  background: #409eff;
  color: #fff;
}

.avatar-ai {
  background: #67c23a;
  color: #fff;
}

/* 气泡 */
.bubble {
  max-width: 75%;
  padding: 10px 16px;
  border-radius: 12px;
  line-height: 1.7;
  font-size: 14px;
  word-break: break-word;
}

.bubble-user {
  background: #409eff;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.bubble-ai {
  background: #fff;
  color: #303133;
  border: 1px solid #e4e7ed;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

/* 打字动画 */
.typing-dots {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-dots span:nth-child(1) { animation-delay: 0s; }
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* 输入区域 */
.chat-input {
  margin-top: 12px;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

/* --- Markdown 渲染样式 --- */

.md-content :deep(h2) {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  margin: 8px 0 4px;
}

.md-content :deep(h3) {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
  margin: 6px 0 4px;
}

.md-content :deep(h4) {
  font-size: 14px;
  font-weight: 700;
  color: #606266;
  margin: 4px 0 2px;
}

.md-content :deep(.md-code-block) {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 12px;
  margin: 6px 0;
  overflow-x: auto;
  font-size: 13px;
}

.md-content :deep(.md-code-block code) {
  background: none;
  padding: 0;
  color: #476582;
}

.md-content :deep(.md-inline-code) {
  background: #f0f2f5;
  color: #e96900;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: monospace;
}

.md-content :deep(strong) {
  color: #303133;
  font-weight: 700;
}

.md-content :deep(.md-ul) {
  margin: 4px 0;
  padding-left: 20px;
}

.md-content :deep(.md-li) {
  line-height: 1.8;
  color: #606266;
}

.md-content :deep(.md-table) {
  border-collapse: collapse;
  margin: 6px 0;
  width: 100%;
  font-size: 13px;
}

.md-content :deep(.md-table td) {
  border: 1px solid #e4e7ed;
  padding: 4px 8px;
}

.md-content :deep(.md-table tr:nth-child(even)) {
  background: #fafafa;
}
</style>
