from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any

_MAX_SESSIONS = 200


class ShortTermMemory:
    def __init__(self, max_turns: int = 30, max_sessions: int = _MAX_SESSIONS) -> None:
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        self._lock = RLock()

    def _session_key(self, session_id: str | None) -> str:
        return (session_id or "default").strip() or "default"

    def add_turn(self, session_id: str | None, question: str, answer: str, mode: str) -> None:
        turn = {
            "question": question.strip()[:600],
            "answer": answer.strip()[:1200],
            "mode": mode,
        }
        key = self._session_key(session_id)
        with self._lock:
            if key in self._sessions:
                self._sessions.move_to_end(key)
            else:
                if len(self._sessions) >= self.max_sessions:
                    self._sessions.popitem(last=False)  # evict least-recently-used session
            turns = self._sessions.setdefault(key, [])
            turns.append(turn)
            if len(turns) > self.max_turns:
                del turns[: len(turns) - self.max_turns]

    def get_turns(self, session_id: str | None, context_window: int) -> list[dict[str, str]]:
        if context_window <= 0:
            return []
        key = self._session_key(session_id)
        with self._lock:
            return list(self._sessions.get(key, [])[-context_window:])

    def format_history(self, session_id: str | None, context_window: int) -> str:
        turns = self.get_turns(session_id, context_window)
        if not turns:
            return ""

        lines = [f"历史对话（最近 {len(turns)} 轮）："]
        for index, turn in enumerate(turns, 1):
            lines.append(f"{index}. 用户：{turn['question']}")
            lines.append(f"{index}. 助手：{turn['answer']}")
        return "\n".join(lines)

    def query_context(self, session_id: str | None, context_window: int, max_chars: int = 180) -> str:
        turns = self.get_turns(session_id, context_window)
        if not turns:
            return ""
        text = " ".join(turn["question"] for turn in turns)
        return text[-max_chars:]

    def clear(self, session_id: str | None) -> dict[str, Any]:
        key = self._session_key(session_id)
        with self._lock:
            removed = len(self._sessions.pop(key, []))
        return {"session_id": key, "removed_turns": removed}

    def count(self, session_id: str | None) -> int:
        key = self._session_key(session_id)
        with self._lock:
            return len(self._sessions.get(key, []))
