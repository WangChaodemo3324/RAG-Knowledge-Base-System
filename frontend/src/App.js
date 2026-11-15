import { computed, onMounted, reactive, ref } from "./vendor/vue.esm-browser.prod.js";

import {
  clearMemory as clearMemoryRequest,
  deleteDocument as deleteDocumentRequest,
  fetchDocuments,
  uploadDocumentsBatch,
  fetchInfo,
  rebuildKnowledgeBaseIndex,
  renderError,
  retryDocument as retryDocumentRequest,
  submitRagRequest,
  submitRagStream,
  uploadDocumentFile,
} from "./api.js?v=20261115-6";
import SourcePanel from "./components/SourcePanel.js?v=20261115-6";
import TopBar from "./components/TopBar.js?v=20260604-1";
import WorkspacePanel from "./components/WorkspacePanel.js?v=20260604-1";
import {
  actionLabel,
  canUseMemoryMode,
  canUseReasoningMode,
  modeHintText,
  modeLabel,
  pendingTextForMode,
  sendTextForMode,
} from "./modes.js?v=20260604-1";
import { loadSessionId } from "./session.js?v=20260528-3";

export default {
  name: "App",
  components: {
    TopBar,
    WorkspacePanel,
    SourcePanel,
  },
  setup() {
    const mode = ref("chat");
    const topK = ref(4);
    const queryMode = ref("AUTO_DOCUMENT");
    const retrievalMode = ref("hybrid_rerank");
    const activeDocument = ref("");
    const reasoning = ref(false);
    const useMemory = ref(true);
    const contextWindow = ref(4);
    const sessionId = ref(loadSessionId());
    const question = ref("");
    const busy = ref(false);
    const selectedFile = ref(null);
    const uploading = ref(false);
    const rebuilding = ref(false);
    const uploadStatus = reactive({ text: "", kind: "" });
    const rebuildStatus = reactive({ text: "", kind: "" });
    const documents = ref([]);
    const documentsLoading = ref(false);
    const documentsError = ref("");
    const docBusyName = ref("");
    const docStatus = reactive({ text: "", kind: "" });
    const info = reactive({
      chunkCount: "-",
      dataFiles: [],
      model: "-",
      keyState: "-",
      ready: false,
      statusText: "初始化中",
      statusKind: "",
    });
    const messages = ref([{ role: "system", text: "知识库正在加载。" }]);
    const sources = ref([]);
    const agentTrace = ref([]);
    const routeInfo = reactive({ route: "", routeReason: "", answerSource: "", confidence: "", router: "" });

    const canUseReasoning = computed(() => canUseReasoningMode(mode.value));
    const canUseMemory = computed(() => canUseMemoryMode(mode.value));
    const selectedFileName = computed(() => selectedFile.value?.name || "未选择文件");
    const sendText = computed(() => sendTextForMode(mode.value));
    const modeHint = computed(() => modeHintText(mode.value, reasoning.value, useMemory.value, contextWindow.value));

    function scrollMessages() {
      queueMicrotask(() => {
        const node = document.querySelector(".messages");
        if (node) node.scrollTop = node.scrollHeight;
      });
    }

    function addMessage(role, text) {
      messages.value.push({ role, text });
      scrollMessages();
    }

    function resetRouteInfo() {
      routeInfo.route = "";
      routeInfo.routeReason = "";
      routeInfo.answerSource = "";
      routeInfo.confidence = "";
      routeInfo.router = "";
    }

    function setMode(nextMode) {
      if (mode.value === nextMode) return;
      mode.value = nextMode;
      sources.value = [];
      agentTrace.value = [];
      resetRouteInfo();
      addMessage("system", `已切换到${modeLabel(nextMode)}。`);
    }

    async function clearMemory() {
      if (busy.value) return;
      try {
        const data = await clearMemoryRequest(sessionId.value);
        addMessage("system", `短期记忆已清空，移除 ${data.removed_turns || 0} 轮历史。`);
      } catch (error) {
        addMessage("system", renderError(error));
      }
    }

    function selectDocument(file) {
      selectedFile.value = file;
      uploadStatus.text = "";
      uploadStatus.kind = "";
    }

    function selectKnowledgeDocument(fileName) {
      const nextDocument = activeDocument.value === fileName ? "" : fileName || "";
      activeDocument.value = nextDocument;
      queryMode.value = activeDocument.value ? "DOCUMENT" : "AUTO_DOCUMENT";
      mode.value = "chat";
      sources.value = [];
      agentTrace.value = [];
      resetRouteInfo();
      if (activeDocument.value) {
        addMessage("system", `已选择当前文档：${activeDocument.value}`);
      } else {
        addMessage("system", "已取消当前文档，切回自动知识问答。");
      }
    }

    async function uploadDocument() {
      if (!selectedFile.value || uploading.value || rebuilding.value) return;

      uploading.value = true;
      uploadStatus.text = "上传中...";
      uploadStatus.kind = "";
      rebuildStatus.text = "";
      rebuildStatus.kind = "";

      try {
        const files = Array.from(selectedFile.value instanceof File ? [selectedFile.value] : selectedFile.value);
        if (files.length > 1) {
          const data = await uploadDocumentsBatch(files);
          const s = data.summary;
          uploadStatus.text = `批量完成：${s.indexed} 成功 / ${s.skipped} 跳过 / ${s.failed} 失败`;
          uploadStatus.kind = s.failed ? "error" : "success";
          const failedNames = data.results.filter((r) => r.error).map((r) => `${r.filename}：${r.error}`);
          if (failedNames.length) {
            addMessage("system", `批量上传部分失败：
${failedNames.join("；")}`);
          } else {
            addMessage("system", `批量上传完成：${s.indexed} 个文档已入库。`);
          }
        } else {
          const data = await uploadDocumentFile(files[0] || selectedFile.value);
          uploadStatus.text = `${data.filename} 已增量入库`;
          uploadStatus.kind = "success";
          addMessage("system", `${data.filename} 上传成功，已增量入库，现在可以参与检索问答。`);
        }
        selectedFile.value = null;
        await Promise.all([loadDocuments(), loadInfo({ resetMessage: false })]);
      } catch (error) {
        uploadStatus.text = renderError(error);
        uploadStatus.kind = "error";
      } finally {
        uploading.value = false;
      }
    }

    async function rebuildKnowledgeBase() {
      if (uploading.value || rebuilding.value) return;

      rebuilding.value = true;
      rebuildStatus.text = "全量重建中...";
      rebuildStatus.kind = "";
      uploadStatus.text = "";
      uploadStatus.kind = "";

      try {
        const data = await rebuildKnowledgeBaseIndex();
        rebuildStatus.text = `完成：${data.data_files?.length || 0} 个文件，${data.chunk_count} 个文本块`;
        rebuildStatus.kind = "success";
        addMessage("system", `知识库已全量重建：${data.data_files?.length || 0} 个文件，${data.chunk_count} 个文本块。`);
        await Promise.all([loadDocuments(), loadInfo({ resetMessage: false })]);
      } catch (error) {
        rebuildStatus.text = renderError(error);
        rebuildStatus.kind = "error";
      } finally {
        rebuilding.value = false;
      }
    }

    async function loadDocuments() {
      documentsLoading.value = true;
      documentsError.value = "";
      try {
        const data = await fetchDocuments();
        documents.value = data.documents || [];
      } catch (error) {
        documentsError.value = renderError(error);
      } finally {
        documentsLoading.value = false;
      }
    }

    async function handleDeleteDocument(fileName) {
      if (docBusyName.value) return;
      if (!window.confirm(`确定删除文档「${fileName}」？索引数据将移除，源文件移入 .trash 目录（可恢复）。`)) return;
      docBusyName.value = fileName;
      docStatus.text = "";
      try {
        await deleteDocumentRequest(fileName);
        docStatus.text = `${fileName} 已删除（源文件移入 .trash）`;
        docStatus.kind = "success";
        if (activeDocument.value === fileName) {
          activeDocument.value = "";
          queryMode.value = "AUTO_DOCUMENT";
          sources.value = [];
        }
        await Promise.all([loadDocuments(), loadInfo({ resetMessage: false })]);
      } catch (error) {
        docStatus.text = renderError(error);
        docStatus.kind = "error";
      } finally {
        docBusyName.value = "";
      }
    }

    async function handleRetryDocument(fileName) {
      if (docBusyName.value) return;
      docBusyName.value = fileName;
      docStatus.text = "";
      try {
        await retryDocumentRequest(fileName);
        docStatus.text = `${fileName} 重试入库成功`;
        docStatus.kind = "success";
        await Promise.all([loadDocuments(), loadInfo({ resetMessage: false })]);
      } catch (error) {
        docStatus.text = renderError(error);
        docStatus.kind = "error";
      } finally {
        docBusyName.value = "";
      }
    }

    async function loadInfo(options = {}) {
      try {
        const data = await fetchInfo();
        info.chunkCount = data.chunk_count;
        info.dataFiles = data.data_files || [];
        info.model = data.deepseek_model;
        info.keyState = data.has_api_key ? "已配置" : "未配置";
        info.ready = data.has_api_key;
        info.statusKind = data.has_api_key ? "ready" : "";
        info.statusText = data.has_api_key ? "已连接" : "未配置 Key";
        // 问答进行中不允许覆盖对话记录（时序竞争会让回答丢失）
        if (options.resetMessage !== false && !busy.value) {
          messages.value = [{ role: "system", text: `知识库已加载：${data.data_files?.length || 0} 个文件，${data.chunk_count} 个文本块。` }];
        }
      } catch (error) {
        info.statusKind = "error";
        info.statusText = "加载失败";
        messages.value = [{ role: "system", text: renderError(error) }];
      }
    }

    async function submitQuestion() {
      const text = question.value.trim();
      if (!text || busy.value) return;

      busy.value = true;
      agentTrace.value = [];
      resetRouteInfo();
      addMessage("user", text);
      const pending = reactive({
        role: "assistant",
        text: pendingTextForMode(mode.value, reasoning.value),
      });
      messages.value.push(pending);

      try {
        const memoryPayload = {
          session_id: sessionId.value,
          use_memory: useMemory.value && canUseMemory.value,
          context_window: Number(contextWindow.value),
        };
        const payload = {
          question: text,
          top_k: Number(topK.value),
          query_mode: mode.value === "chat" ? (activeDocument.value ? "DOCUMENT" : "AUTO_DOCUMENT") : "OPEN_CHAT",
          retrieval_mode: retrievalMode.value,
          file_name: mode.value === "chat" && activeDocument.value ? activeDocument.value : "",
          reasoning: reasoning.value,
          ...memoryPayload,
        };

        if (mode.value === "chat") {
          // SSE streaming with non-streaming fallback
          let streamed = false;
          try {
            streamed = await submitRagStream(payload, {
              onSources: (items) => {
                sources.value = items || [];
              },
              onToken: (token) => {
                pending.text += token;
                scrollMessages();
              },
              onDone: (event) => {
                if (event.answer) pending.text = event.answer;
                scrollMessages();
              },
              onError: (detail) => {
                pending.text += `\n\n[${detail}]`;
              },
            });
          } catch (streamError) {
            streamed = false; // fall back below
          }
          if (streamed) {
            question.value = "";
            return;
          }
          // non-streaming fallback for chat mode
          const data = await submitRagRequest(mode.value, payload);
          pending.text = data.answer || "没有返回答案。";
          sources.value = data.sources || [];
          agentTrace.value = data.tool_traces || data.trace || [];
          routeInfo.route = data.route || "";
          routeInfo.routeReason = data.route_reason || "";
          routeInfo.answerSource = data.answer_source || "";
          routeInfo.confidence = data.route_confidence ?? "";
          routeInfo.router = data.route_router || "";
          question.value = "";
          return;
        }

        const data = await submitRagRequest(mode.value, payload);

        if (mode.value === "web" || mode.value === "agent") {
          pending.text = data.answer || "没有返回答案。";
          sources.value = data.sources || [];
          agentTrace.value = data.tool_traces || data.trace || [];
          routeInfo.route = data.route || "";
          routeInfo.routeReason = data.route_reason || "";
          routeInfo.answerSource = data.answer_source || "";
          routeInfo.confidence = data.route_confidence ?? "";
          routeInfo.router = data.route_router || "";
        } else {
          const previews = data.results
            .map((item) => `[${item.index}] ${item.preview || item.content || ""}`)
            .join("\n\n");
          pending.text = `检索到 ${data.results.length} 条相关资料：\n\n${previews}`;
          sources.value = data.results || [];
          agentTrace.value = [];
          resetRouteInfo();
        }
        question.value = "";
      } catch (error) {
        pending.text = renderError(error);
        sources.value = [];
        agentTrace.value = [];
        resetRouteInfo();
      } finally {
        busy.value = false;
      }
    }

    onMounted(() => {
      loadInfo();
      loadDocuments();
    });

    return {
      mode,
      topK,
      queryMode,
      retrievalMode,
      activeDocument,
      reasoning,
      useMemory,
      contextWindow,
      canUseReasoning,
      canUseMemory,
      question,
      busy,
      selectedFile,
      uploading,
      rebuilding,
      documents,
      documentsLoading,
      documentsError,
      docBusyName,
      docStatus,
      handleDeleteDocument,
      handleRetryDocument,
      uploadStatus,
      rebuildStatus,
      selectedFileName,
      info,
      messages,
      sources,
      agentTrace,
      routeInfo,
      sendText,
      modeHint,
      actionLabel,
      clearMemory,
      selectDocument,
      selectKnowledgeDocument,
      uploadDocument,
      rebuildKnowledgeBase,
      setMode,
      submitQuestion,
    };
  },
  template: `
    <main class="shell">
      <TopBar :info="info" />

      <section class="layout">
        <WorkspacePanel
          :mode="mode"
          :top-k="topK"
          :retrieval-mode="retrievalMode"
          :active-document="activeDocument"
          :info="info"
          :reasoning="reasoning"
          :use-memory="useMemory"
          :context-window="contextWindow"
          :can-use-reasoning="canUseReasoning"
          :can-use-memory="canUseMemory"
          :question="question"
          :busy="busy"
          :messages="messages"
          :send-text="sendText"
          :mode-hint="modeHint"
          @change-mode="setMode"
          @change-active-document="selectKnowledgeDocument"
          @change-reasoning="reasoning = $event"
          @change-memory="useMemory = $event"
          @change-context-window="contextWindow = $event"
          @change-top-k="topK = $event"
          @change-retrieval-mode="retrievalMode = $event"
          @change-question="question = $event"
          @clear-memory="clearMemory"
          @submit-question="submitQuestion"
        />

        <SourcePanel
          :info="info"
          :documents="documents"
          :documents-loading="documentsLoading"
          :documents-error="documentsError"
          :doc-busy-name="docBusyName"
          :doc-status="docStatus"
          @delete-document="handleDeleteDocument"
          @retry-document="handleRetryDocument"
          :use-memory="useMemory"
          :can-use-memory="canUseMemory"
          :context-window="contextWindow"
          :sources="sources"
          :agent-trace="agentTrace"
          :route-info="routeInfo"
          :uploading="uploading"
          :rebuilding="rebuilding"
          :selected-file="selectedFile"
          :selected-file-name="selectedFileName"
          :active-document="activeDocument"
          :upload-status="uploadStatus"
          :rebuild-status="rebuildStatus"
          :action-label="actionLabel"
          @select-document="selectDocument"
          @select-knowledge-document="selectKnowledgeDocument"
          @upload-document="uploadDocument"
          @rebuild-knowledge-base="rebuildKnowledgeBase"
        />
      </section>
    </main>
  `,
};
