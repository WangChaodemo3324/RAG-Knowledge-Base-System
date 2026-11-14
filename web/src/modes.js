export function canUseReasoningMode(mode) {
  return mode === "chat" || mode === "web" || mode === "agent";
}

export function canUseMemoryMode(mode) {
  return mode === "chat" || mode === "web" || mode === "agent";
}

export function modeLabel(mode) {
  if (mode === "chat") return "文档问答";
  if (mode === "web") return "开放提问";
  if (mode === "agent") return "自动模式";
  return "检索模式";
}

export function sendTextForMode(mode) {
  if (mode === "chat") return "生成答案";
  if (mode === "web") return "开放回答";
  if (mode === "agent") return "自动回答";
  return "检索资料";
}

export function pendingTextForMode(mode, reasoning) {
  if (mode === "agent") return "正在自动选择工具并回答...";
  if (mode === "web") return reasoning ? "正在判断是否需要联网并推理..." : "正在判断回答来源...";
  if (mode === "chat") return reasoning ? "正在推理并生成答案..." : "正在生成答案...";
  return "正在检索资料...";
}

export function modeHintText(mode, reasoning, useMemory, contextWindow) {
  const canUseMemory = canUseMemoryMode(mode);
  const canUseReasoning = canUseReasoningMode(mode);
  const memoryText = canUseMemory
    ? useMemory
      ? `会带入最近 ${contextWindow} 轮短期记忆。`
      : "短期记忆关闭。"
    : "检索模式不使用短期记忆。";
  const reasoningText = canUseReasoning
    ? reasoning
      ? "推理已开启，适合复杂问题，速度会更慢。"
      : "推理关闭，响应速度更快。"
    : "检索模式不调用大模型。";

  if (mode === "chat") return `文档问答：基于本地企业知识库生成答案。${reasoningText}${memoryText}`;
  if (mode === "web") return `开放提问：可直接回答；明确要求联网或涉及实时信息时会搜索网页。${reasoningText}${memoryText}`;
  if (mode === "agent") return `自动模式：系统自动选择本地知识库或联网工具。${reasoningText}${memoryText}`;
  return `检索模式：只返回本地资料片段，不调用 DeepSeek，不消耗 API 额度。${reasoningText}${memoryText}`;
}

export function actionLabel(action) {
  if (action === "local_search") return "本地检索";
  if (action === "web_search") return "联网搜索";
  if (action === "finish") return "生成答案";
  return action || "执行";
}
