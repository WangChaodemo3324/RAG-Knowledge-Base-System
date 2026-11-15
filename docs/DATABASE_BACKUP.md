# 数据库备份与恢复

## 备份（物理一致的自定义格式 dump）

```bash
./scripts/backup-db.sh              # 输出到 ./backups/rag_backup_<时间戳>.dump
./scripts/backup-db.sh /path/to/dir # 自定义输出目录
```

- 使用 `pg_dump -Fc`（自定义压缩格式），恢复用 `pg_restore`
- 脚本内置体积下限自检（<10KB 视为可疑并退出码 2）
- 建议频率：每次全量重建或上传重要文档后；生产环境建议每日定时（crontab 示例：`0 2 * * * /path/to/scripts/backup-db.sh`）

## 恢复

```bash
./scripts/restore-db.sh ./backups/rag_backup_YYYYMMDD_HHMMSS.dump            # 恢复到临时验证库 rag_restore_test
./scripts/restore-db.sh ./backups/xxx.dump rag                               # 恢复到正式库（会先 DROP 重建，谨慎！）
```

恢复脚本在临时库上验证 `child_chunks` 行数后输出清理提示。

## 已执行的验证（2026-11-15）

1. `backup-db.sh` → `rag_backup_20261115_033118.dump`（2,542,195 字节）
2. `restore-db.sh` → 临时库 `rag_restore_test` 恢复成功，`child_chunks` = 417 行，与正式库一致
3. 临时库已清理

## 容器重启持久化（已验证）

`docker compose restart db` + `restart api` 前后快照一致：child_chunks=417、alembic_version=0002、active 版本不变。pgdata 具名卷是持久层，**`docker compose down -v` 才会删除数据卷**。

## 部署漂移警示（真实案例）

容器镜像在构建时**复制了当时的 migrations/ 目录**。若在宿主机新增迁移并执行（主库 revision 前进），而镜像未重建，容器启动时的 `alembic upgrade head` 会报 `Can't locate revision` 进入重启循环。**新增迁移后必须 `docker compose up -d api --build`**；多实例环境改为部署流程独立执行迁移。

## 磁盘占用

pgdata 卷当前 ~128MB（3 个蓝绿版本 × 完整数据 + 0002 后 jsonb）。历史版本可通过 `POST /index/prune`（管理端点）清理，保留最近 N 个 retired 版本。
