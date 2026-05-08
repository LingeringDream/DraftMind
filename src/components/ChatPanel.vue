<template>
  <div class="chat-container">
    <div class="chat-messages" ref="chatContainer">
      <div v-for="(msg, idx) in chatHistory" :key="idx">
        <div class="message user"><strong>用户：</strong>{{ msg.question }}</div>
        <div class="message assistant"><strong>AI：</strong>{{ msg.answer }}</div>
      </div>
      <div v-if="loading" class="message assistant"><strong>AI：</strong>思考中...</div>
    </div>
    <div class="chat-input">
      <el-input
        v-model="question"
        type="textarea"
        :rows="3"
        placeholder="请输入问题，例如：这个零件的配合公差是多少？"
        @keydown.ctrl.enter="sendQuestion"
      />
      <el-button type="primary" @click="sendQuestion" :loading="loading">发送</el-button>
    </div>
    <el-button v-if="chatHistory.length" @click="clearChat" plain>清除对话</el-button>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useDrawingStore } from '@/stores/drawing'

const store = useDrawingStore()
const chatHistory = computed(() => store.currentDrawing?.chatHistory || [])
const loading = ref(false)
const question = ref('')
const chatContainer = ref(null)

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
</script>

<style scoped>
.chat-container {
  height: 500px;
  display: flex;
  flex-direction: column;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  padding: 12px;
  border-radius: 4px;
}
.message {
  margin-bottom: 12px;
}
.user {
  text-align: right;
}
.assistant {
  text-align: left;
}
.chat-input {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}
</style>