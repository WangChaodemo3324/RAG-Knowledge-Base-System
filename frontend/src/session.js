export function loadSessionId() {
  const key = "rag_session_id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const next = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(key, next);
  return next;
}
