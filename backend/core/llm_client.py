from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI


def build_llm(config: dict[str, str], reasoning: bool, timeout: int) -> ChatOpenAI:
    llm_args: dict[str, Any] = {
        "model": config["model"],
        "timeout": timeout,
        "max_retries": 2,
        "api_key": config["api_key"],
        "base_url": config["base_url"],
        "extra_body": {
            "thinking": {
                "type": "enabled" if reasoning else "disabled",
            }
        },
    }
    if reasoning:
        llm_args["reasoning_effort"] = "high"
    else:
        llm_args["temperature"] = 0
    return ChatOpenAI(**llm_args)
