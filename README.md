# RAG 知识库系统（LangChain 实现）

基于 LangChain + FastAPI 的企业知识库问答系统：本地知识库检索问答、联网搜索问答、ReAct Agent 自动编排三合一，附带完整的查询路由、混合检索与重排序链路。

## 核心特性

- **父子分块索引**：子块（约 700 字，语义边界切分）用于召回，命中后展开父块（约 1800 字）提供给大模型，兼顾召回精度与上下文完整性
- **混合检索**：BGE-M3 向量检索 + jieba 分词 BM25 关键字检索 → RRF 融合 → `bge-reranker-base` 精排
- **六路查询路由**：规则特征提取 → 证据充分性检查 → LLM 路由兜底，在「知识库 / 联网 / 先库后网 / 直接回答 / 澄清 / 无证据」之间自动决策；文档模式强制走本地库，私有内部问题证据不足时拒绝用公网资料编造
- **ReAct Agent**：LLM 决策 `local_search / web_search / finish`，多步工具调用并输出完整 trace
- **联网搜索**：Tavily 主链路，失败自动重试并 fallback 到 DuckDuckGo
- **会话记忆**：会话级短期记忆（最近 30 轮），支持上下文窗口控制
- **增量入库**：上传 PDF/MD/TXT 即增量索引，指纹去重；启动时自检索引健康度，不一致自动全量重建

## 项目结构

```
backend/
├── main.py            # FastAPI 入口，12 个 REST 端点
├── core/              # 配置加载、LLM 客户端
├── indexing/          # 离线索引：分块、嵌入、Chroma、父子存储、manifest
├── knowledge/         # 在线检索门面（子块命中 → 展开父块）
├── services/
│   ├── routing/       # 查询路由子系统（特征/证据/LLM 路由/trace 日志）
│   ├── hybrid_search_service.py   # 向量 + BM25 + RRF
│   ├── rerank_service.py          # 重排序
│   ├── qa_service.py              # 三种回答：知识库/直接 LLM/联网
│   ├── agent_service.py           # ReAct Agent
│   └── memory_store.py            # 会话短期记忆
├── chat/              # 用户模式（文档/自动/开放）→ 执行模式编排
└── tools/             # web_search / weather 工具
frontend/              # 原生 JS 前端（"/" 路径）
web/                   # 独立版前端（"/web" 路径）
legacy/rag.py          # 最早的课程演示脚本
resource data/         # 示例语料（1 份 PDF 产品手册 + 5 份制度文档）
tools/                 # 检索效果测试脚本
```

## 快速开始

```bash
pip install -r requirements.txt

# 配置密钥（参考 .env.example）
cp .env.example .env
# 在 .env 中填入 DEEPSEEK_API_KEY 和 TAVILY_API_KEY

uvicorn api:app --port 8012
# 访问 http://127.0.0.1:8012 （前端）、http://127.0.0.1:8012/docs （API 文档）
```

首次启动会自动构建本地索引（需要下载 BGE-M3 ONNX 模型，约 2GB，之后走本地缓存）。

## 主要 API

| 端点 | 说明 |
| --- | --- |
| `POST /chat` | 知识库问答（支持文档/自动/开放三种模式） |
| `POST /agent-chat` | ReAct Agent 自动编排问答 |
| `POST /web-chat` | 联网搜索问答 |
| `POST /search` | 向量检索 |
| `POST /hybrid-search` | 向量 + BM25 + RRF 混合检索 |
| `POST /rerank-search` | 混合检索 + 重排序 |
| `POST /documents/upload` | 上传文档并增量入库 |
| `POST /knowledge-base/rebuild` | 全量重建索引 |
| `POST /memory/clear` | 清空会话记忆 |

## 环境变量

详见 `.env.example` 与 `backend/core/config.py`：`DEEPSEEK_API_KEY`、`TAVILY_API_KEY`、`RAG_EMBEDDING_MODEL`（默认 `BAAI/bge-m3`）、`RAG_RERANK_MODEL`（默认 `BAAI/bge-reranker-base`）及分块、检索、联网搜索等参数。
