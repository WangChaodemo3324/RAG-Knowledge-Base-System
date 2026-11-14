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

export async function rebuildKnowledgeBaseIndex() {
  const response = await fetch("/knowledge-base/rebuild", { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `重建失败：${response.status}`);
  }
  return data;
}
