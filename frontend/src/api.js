export function renderError(error) {
  return error?.message || "请求失败";
}

export async function requestJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `请求失败：${response.status}`);
  }
  return data;
}

export async function fetchInfo() {
  const response = await fetch("/info");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `加载失败：${response.status}`);
  }
  return data;
}

export function clearMemory(sessionId) {
  return requestJson("/memory/clear", { session_id: sessionId });
}

export function submitRagRequest(mode, payload) {
  if (mode === "chat") return requestJson("/chat", payload);
  if (mode === "web") return requestJson("/web-chat", payload);
  if (mode === "agent") return requestJson("/agent-chat", payload);
  return requestJson("/search", { query: payload.question, top_k: payload.top_k });
}

export async function submitRagStream(payload, handlers = {}) {
  const response = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `流式请求失败：${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      for (const line of block.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") return true;
        try {
          const event = JSON.parse(data);
          if (event.type === "sources") handlers.onSources?.(event.sources);
          else if (event.type === "token") handlers.onToken?.(event.text);
          else if (event.type === "done") handlers.onDone?.(event);
          else if (event.type === "error") handlers.onError?.(event.detail);
        } catch {
          /* ignore malformed keepalive fragments */
        }
      }
    }
  }
  return false;
}

export async function uploadDocumentFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/documents/upload", {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `上传失败：${response.status}`);
  }
  return data;
}

export async function uploadDocumentsBatch(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const response = await fetch("/documents/upload-batch", {
    method: "POST",
    body: formData,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `批量上传失败：${response.status}`);
  }
  return data;
}

export async function rebuildKnowledgeBaseIndex() {
  const response = await fetch("/knowledge-base/rebuild", { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `重建失败：${response.status}`);
  }
  return data;
}

export async function fetchDocuments() {
  const response = await fetch("/documents");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `文档列表加载失败：${response.status}`);
  }
  return data;
}

export async function deleteDocument(fileName) {
  const response = await fetch(`/documents/${encodeURIComponent(fileName)}`, { method: "DELETE" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `删除失败：${response.status}`);
  }
  return data;
}

export async function retryDocument(fileName) {
  const response = await fetch(`/documents/${encodeURIComponent(fileName)}/retry`, { method: "POST" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `重试失败：${response.status}`);
  }
  return data;
}
