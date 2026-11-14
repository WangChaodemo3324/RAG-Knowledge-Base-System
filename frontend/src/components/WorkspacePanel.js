export default {
  name: "WorkspacePanel",
  props: {
    mode: { type: String, required: true },
    topK: { type: Number, required: true },
    retrievalMode: { type: String, required: true },
    activeDocument: { type: String, default: "" },
    info: { type: Object, required: true },
    reasoning: { type: Boolean, required: true },
    useMemory: { type: Boolean, required: true },
    contextWindow: { type: Number, required: true },
    canUseReasoning: { type: Boolean, required: true },
    canUseMemory: { type: Boolean, required: true },
    question: { type: String, required: true },
    busy: { type: Boolean, required: true },
    messages: { type: Array, required: true },
    sendText: { type: String, required: true },
    modeHint: { type: String, required: true },
  },
  emits: [
    "change-mode",
    "change-active-document",
    "change-retrieval-mode",
    "change-reasoning",
    "change-memory",
    "change-context-window",
    "change-top-k",
    "change-question",
    "clear-memory",
    "submit-question",
  ],
  data() {
    return {
      advancedOpen: false,
    };
  },
  computed: {
    documentScope() {
      return this.activeDocument || "";
    },
  },
  template: `
    <section class="workspace" aria-label="问答区">
      <div class="toolbar product-toolbar">
        <div class="segmented main-modes" role="tablist" aria-label="模式">
          <button :class="{ active: mode === 'chat' }" type="button" @click="$emit('change-mode', 'chat')">文档问答</button>
          <button :class="{ active: mode === 'web' }" type="button" @click="$emit('change-mode', 'web')">开放提问</button>
          <button :class="{ active: mode === 'agent' }" type="button" @click="$emit('change-mode', 'agent')">自动模式</button>
        </div>
        <button class="advanced-toggle" type="button" @click="advancedOpen = !advancedOpen">
          {{ advancedOpen ? '收起高级' : '高级设置' }}
        </button>
      </div>

      <div class="summary-bar">
        <div class="kb-summary">
          知识库：已加载 <strong>{{ info.dataFiles.length }}</strong> 个文档，<strong>{{ info.chunkCount }}</strong> 个文本块
        </div>
        <label v-if="mode === 'chat'" class="scope-control">
          问答范围
          <select :value="documentScope" @change="$emit('change-active-document', $event.target.value)">
            <option value="">自动选择文档</option>
            <option v-for="file in info.dataFiles" :key="file" :value="file">{{ file }}</option>
          </select>
        </label>
      </div>

      <div v-if="advancedOpen" class="advanced-panel">
        <label :class="['reasoning-toggle', { disabled: !canUseMemory }]">
          <input
            type="checkbox"
            :checked="useMemory"
            :disabled="!canUseMemory"
            @change="$emit('change-memory', $event.target.checked)"
          />
          <span class="switch" aria-hidden="true"></span>
          <span>记忆</span>
        </label>
        <label class="settings">
          记忆轮数
          <select :value="contextWindow" :disabled="!canUseMemory" @change="$emit('change-context-window', Number($event.target.value))">
            <option :value="2">2</option>
            <option :value="4">4</option>
            <option :value="6">6</option>
            <option :value="8">8</option>
          </select>
        </label>
        <label :class="['reasoning-toggle', { disabled: !canUseReasoning }]">
          <input
            type="checkbox"
            :checked="reasoning"
            :disabled="!canUseReasoning"
            @change="$emit('change-reasoning', $event.target.checked)"
          />
          <span class="switch" aria-hidden="true"></span>
          <span>推理</span>
        </label>
        <label v-if="mode === 'chat'" class="settings">
          检索策略
          <select :value="retrievalMode" @change="$emit('change-retrieval-mode', $event.target.value)">
            <option value="hybrid_rerank">混合精排</option>
            <option value="vector">向量检索</option>
          </select>
        </label>
        <label class="settings">
          引用数量
          <select :value="topK" @change="$emit('change-top-k', Number($event.target.value))">
            <option :value="2">2</option>
            <option :value="4">4</option>
            <option :value="6">6</option>
            <option :value="8">8</option>
          </select>
        </label>
        <button class="clear-memory" type="button" :disabled="busy" @click="$emit('clear-memory')">清空记忆</button>
        <div class="advanced-meta">
          <span>模型：{{ info.model }}</span>
          <span>Key：{{ info.keyState }}</span>
        </div>
      </div>

      <div class="messages">
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          {{ message.text }}
        </div>
      </div>

      <form class="composer" @submit.prevent="$emit('submit-question')">
        <textarea
          :value="question"
          rows="2"
          placeholder="请输入问题，例如：生产环境发布失败后如何回滚？"
          @input="$emit('change-question', $event.target.value)"
        ></textarea>
        <button class="send" type="submit" :disabled="busy || !question.trim()">{{ sendText }}</button>
      </form>
    </section>
  `,
};
