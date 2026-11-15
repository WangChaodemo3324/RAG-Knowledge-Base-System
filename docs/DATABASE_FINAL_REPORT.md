# 数据库终审报告（DATABASE_FINAL_REPORT）

## 1. Schema 与迁移

- 迁移链：0001（五表 + pgvector 扩展 + HNSW 索引）→ 0002（json→jsonb 契约对齐）——两个版本均有升级/降级/升级循环测试（test_migrations.py，独立 rag_test 库实测）
- `alembic_version` 当前值（正式库）：0002
- 模型↔数据库契约：由迁移测试固化（vector/1024 维、jsonb、HNSW 索引名断言）

## 2. 数据一致性实测（V3.5 验收轮）

| 检查 | 结果 |
| --- | --- |
| 索引行与文档记录一致性 | validate_version 校验器：0 孤儿、0 计数不符 |
| 删除级联 | document 行删除 → 父/子块 CASCADE 清理（文档生命周期测试实证） |
| BM25 语料一致性 | 删除文档后语料行数同步收缩（测试实证） |
| 蓝绿版本隔离 | active 版本数据独立于 retired 版本；切换零读中断（压测 180 次重建期读取 0 失败） |
| 测试污染 | 发现批量测试语料污染正式库 → 三层清理（DB/磁盘/git）+ 测试自清理化，基线恢复（139 子块） |

## 3. 性能（EXPLAIN ANALYZE 实测）

主检索查询（139 子块 / 300 父块 / 70 文档记录，含多版本累积）：

```
Index Scan using ix_child_chunks_version_id on child_chunks (139 rows)
→ Hash Join parent_chunks → Sort (top-N heapsort 39kB)
Planning 1.695 ms | Execution 1.225 ms
```

- 规划器在百级规模正确选择精确 KNN 排序（HNSW 留给规模化）——非缺陷
- **发现**：retired 版本累积使父块表膨胀（10 版本 × 30 父块）→ `POST /index/prune` 保留策略已实现；建议重建频繁时每周 prune 一次
- 连接池：pool 5 + overflow 5 + connect_timeout 10s + pool_recycle 30min——单机规模合理

## 4. 备份与恢复（V3.5 复核）

- `backup-db.sh`：2.5MB dump 实测 + 保留策略（RETAIN=7 自动清理）
- `restore-db.sh`：临时库恢复 417 行一致实测后清理
- 重启持久化：db/api 双重启后 417 行 + 迁移版本不变（实测）
- 卷管理：pgdata（数据）/ hf_cache（模型，V3.5 新增——9P mmap 问题解法，见 DEPLOYMENT_ACCEPTANCE_REPORT.md）/ resource data（bind mount）

## 5. MVCC 与事务

- 增量入库单事务原子交换（读侧 READ COMMITTED 无中间态——跨会话测试实证）
- 全量构建多事务 + 末段校验切换；失败路径全部回滚验证（故障注入 10+2 场景）
- 心跳恢复：stale_seconds=300，活跃构建不被误杀（V2 压测缺陷修复后回归验证）

## 6. 遗留

- retired 版本累积（已提供 prune 工具）
- 子块表未来百万级时需评估 HNSW 参数与 ef_search 调优（当前规模无瓶颈）
