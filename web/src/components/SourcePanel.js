export default {
  name: "SourcePanel",
  props: {
    info: { type: Object, required: true },
    useMemory: { type: Boolean, required: true },
    canUseMemory: { type: Boolean, required: true },
    contextWindow: { type: Number, required: true },
    sources: { type: Array, required: true },
    agentTrace: { type: Array, required: true },
    routeInfo: { type: Object, required: true },
    uploading: { type: Boolean, required: true },
    rebuilding: { type: Boolean, required: true },
    selectedFile: { type: Object, default: null },
    selectedFileName: { type: String, required: true },
    activeDocument: { type: String, default: "" },
    uploadStatus: { type: Object, required: true },
    rebuildStatus: { type: Object, required: true },
    actionLabel: { type: Function, required: true },
  },
  emits: ["select-document", "select-knowledge-document", "upload-document", "rebuild-knowledge-base"],
  watch: {
    selectedFile(value) {
      if (!value && this.$refs.uploadInput) {
        this.$refs.uploadInput.value = "";
      }
    },
  },
  methods: {
    openUploadPicker() {
      if (this.uploading || this.rebuilding) return;
      this.$refs.uploadInput?.click();
    },
    selectDocument(event) {
      this.$emit("select-document", event.target.files?.[0] || null);
    },
    sourceScore(source) {
      const value = source.rerank_score || source.metadata?.rerank_score;
      return typeof value === "number" ? value.toFixed(3) : value || "";
    },
  },
  template: `
    <aside class="sources" aria-label="侧边栏">
      <section class="side-card">
        <div class="side-head">
          <h2>知识库管理</h2>
        </div>
        <div class="meta">
          <div class="kb-stat">
            <span>已加载</span>
            <strong>{{ info.dataFiles.length }} 个文档 / {{ info.chunkCount }} 个文本块</strong>
          </div>

          <input ref="uploadInput" class="upload-input" type="file" accept=".pdf,.md,.txt" @change="selectDocument" />
          <div class="upload-actions">
            <button class="upload-pick" type="button" :disabled="uploading || rebuilding" @click="openUploadPicker">上传文档</button>
            <button class="rebuild-submit" type="button" :disabled="uploading || rebuilding" @click="$emit('rebuild-knowledge-base')">
              {{ rebuilding ? '重建中' : '重建索引' }}
            </button>
          </div>
          <div v-if="selectedFile" class="upload-file">{{ selectedFileName }}</div>
          <button
            v-if="selectedFile"
            class="upload-submit"
            type="button"
            :disabled="uploading || rebuilding"
            @click="$emit('upload-document')"
          >
            {{ uploading ? '上传中' : '确认入库' }}
          </button>
          <div v-if="uploadStatus.text" :class="['upload-status', uploadStatus.kind]">{{ uploadStatus.text }}</div>
          <div v-if="rebuildStatus.text" :class="['upload-status', rebuildStatus.kind]">{{ rebuildStatus.text }}</div>

          <div class="scope-state">
            当前范围：<strong>{{ activeDocument || '自动选择文档' }}</strong>
          </div>
          <details class="document-switcher">
            <summary>切换文档</summary>
            <div class="file-list">
              <button
                type="button"
                :class="{ active: !activeDocument }"
                @click="$emit('select-knowledge-document', '')"
              >
                自动选择文档
              </button>
              <button
                v-for="file in info.dataFiles"
                :key="file"
                type="button"
                :class="{ active: file === activeDocument }"
                @click="$emit('select-knowledge-document', file)"
              >
                {{ file }}
              </button>
            </div>
          </details>
        </div>
      </section>

      <section class="side-card source-card">
        <div class="side-head">
          <h2>引用来源</h2>
        </div>
        <div v-if="routeInfo.answerSource || routeInfo.route" class="route-state">
          <div>回答来源：<strong>{{ routeInfo.answerSource || routeInfo.route }}</strong></div>
          <div v-if="routeInfo.router || routeInfo.confidence !== ''" class="route-meta">
            路由器：{{ routeInfo.router || '-' }}
            <span v-if="routeInfo.confidence !== ''"> / 置信度：{{ routeInfo.confidence }}</span>
          </div>
          <small v-if="routeInfo.routeReason">{{ routeInfo.routeReason }}</small>
        </div>
        <div v-if="agentTrace.length" class="trace-list">
          <div v-for="step in agentTrace" :key="step.step" class="trace-item">
            <strong>{{ step.step }}. {{ actionLabel(step.action) }}</strong>
            <span v-if="step.query">{{ step.query }}</span>
            <div v-if="step.provider || step.status" class="trace-meta">
              <span v-if="step.provider">服务：{{ step.provider }}</span>
              <span v-if="step.status">状态：{{ step.status }}</span>
              <span v-if="step.result_count !== undefined">结果：{{ step.result_count }}</span>
              <span v-if="step.duration_ms !== undefined">耗时：{{ step.duration_ms }}ms</span>
              <span v-if="step.retry_count">重试：{{ step.retry_count }}</span>
              <span v-if="step.fallback_from">fallback：{{ step.fallback_from }}</span>
            </div>
            <small>{{ step.summary }}</small>
          </div>
        </div>
        <div class="source-list">
          <div v-if="!sources.length" class="empty">暂无引用。</div>
          <article v-for="source in sources" :key="source.index" class="source-item">
            <div class="source-title">
              <span>[{{ source.index }}] {{ source.title || source.source || '资料片段' }}</span>
            </div>
            <a v-if="source.url" class="source-url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.url }}</a>
            <div v-if="source.matched_child_id" class="source-meta-line">匹配子块：{{ source.matched_child_id }}</div>
            <div v-if="source.parent_id" class="source-meta-line">回填父块：{{ source.parent_id }}</div>
            <div v-if="sourceScore(source)" class="source-meta-line">rerank_score：{{ sourceScore(source) }}</div>
            <div class="source-text">{{ source.preview || source.content }}</div>
          </article>
        </div>
      </section>
    </aside>
  `,
};
