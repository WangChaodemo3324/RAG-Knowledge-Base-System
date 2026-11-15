# 数据库表结构

Schema 由 Alembic 管理：`migrations/versions/0001_initial_schema.py`。向量列使用 pgvector `vector(1024)`（BGE-M3 dense 维度）。

## index_versions — 索引版本（蓝绿载体）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | serial PK | |
| name | varchar(80) UNIQUE | 版本名，如 `v_20261115120000_a1b2` |
| status | varchar(20) INDEX | building / active / retired / failed |
| is_active | boolean | **唯一部分索引** `WHERE is_active`：全表至多一个 active |
| embedding_model | varchar(200) | 构建时嵌入模型名 |
| embedding_dim | integer | 默认 1024 |
| metadata_schema_version | varchar(40) | ChunkMetadataBuilder 契约版本（当前 "5"） |
| chunk_settings | jsonb | 分块参数快照（父/子块大小、重叠、分隔符） |
| source_manifest | jsonb | 构建结果文件清单（指纹、块数） |
| notes / created_at / activated_at / retired_at | | |

## documents — 文件级记录（吸收 manifest.json）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | serial PK | |
| version_id | FK → index_versions (CASCADE) INDEX | |
| file_name | varchar(500) | UNIQUE(version_id, file_name) |
| file_hash | varchar(64) | SHA-256，增量去重依据 |
| file_size | bigint | |
| modified_at | varchar(64) | |
| status | varchar(20) | indexed / failed |
| document_count / parent_count / chunk_count | integer | loader 文档数、父块数、子块数 |
| error | text | |
| indexed_at | timestamptz | |

## parent_chunks — 父块（吸收 parent_store.json）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | bigserial PK | 内部主键（child_chunks.parent_pk 引用） |
| version_id | FK (CASCADE) INDEX | |
| document_id | FK (CASCADE) INDEX | |
| parent_id | varchar(80) | 业务 ID：`{file_hash16}-{file_key}-p{n}`，UNIQUE(version_id, parent_id) |
| parent_index | integer | 文档内序号 |
| content | text | |
| metadata | jsonb | 原 ChunkMetadataBuilder 父块元数据 |

## child_chunks — 子块 + 向量（吸收 child_store.json + Chroma）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | bigserial PK | |
| version_id | FK (CASCADE) INDEX | |
| document_id | FK (CASCADE) INDEX | |
| parent_pk | FK → parent_chunks (CASCADE) INDEX | |
| child_id | varchar(80) | `{parent_id}-c{n}`，UNIQUE(version_id, child_id) |
| child_index | integer | 全版本内序号 |
| content | text | |
| **embedding** | **vector(1024) NOT NULL** | HNSW 索引 `vector_cosine_ops` |
| metadata | jsonb | 子块元数据 |

## index_tasks — 索引任务状态机

| 列 | 类型 | 说明 |
| --- | --- | --- |
| id | serial PK | |
| task_type | varchar(40) | full_rebuild / incremental |
| status | varchar(20) INDEX | running / succeeded / failed |
| version_id | FK → index_versions (SET NULL) | |
| message / error | text | |
| created_at / updated_at | timestamptz | |

## 关键设计点

1. **单 active 约束**：`ux_index_versions_one_active` 部分唯一索引保证版本切换原子且全局唯一
2. **级联删除**：删版本即清全部 chunks/documents；任务行 SET NULL 保留审计
3. **HNSW 索引**：`ix_child_chunks_embedding_hnsw USING hnsw (embedding vector_cosine_ops)`；当前 139 子块规模下 HNSW 与精确扫描都够用，索引保留规模化路径
4. **扩展初始化**：`CREATE EXTENSION vector` 同时出现在容器 init 脚本与迁移 0001（幂等）
5. 旧 `parent_store.json / child_store.json / manifest.json` 中的数据结构由 `documents + parent_chunks + child_chunks + index_versions.source_manifest` 共同吸收
