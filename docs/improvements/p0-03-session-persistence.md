# P0-3 会话持久化（内存 LRU → SQLite 落盘）

**状态（2026-09-23，本地工作树）：基础版已接线。** `SessionStore` 用 SQLite 保存消息、逐条时间和滚动摘要；LRU 未命中与重启时恢复，`/api/history` 恢复前端文本，`/api/reset` 删除会话与用户记忆。默认路径 `data/sessions.db`，可设空关闭。写入失败会记录日志并在本轮回复显示未保存警示。当前 CLI 在落盘启用时只允许本机监听；非本机部署仍需完整鉴权，设备级重启验收尚未完成。SQLite 读写目前仍是同步调用，后续应改为离开事件循环执行。

## 差距（airi 怎么做）

airi 的会话历史持久化在浏览器 IndexedDB（`airi/packages/stage-ui/src/database/storage.ts`，unstorage + indexeddb driver），配套云同步的 outbox/tombstone 对账（`repos/chat-sessions.repo.ts`）。云同步我们不学，但「历史与摘要不因进程重启丢失」是它的底线。

## 我们的现状

`frontend/web.py` 的 `get_session()`：会话是进程内 dict，上限 128、LRU 剔空闲；对话历史与滚动压缩摘要（`dialogue/memory.py` 的 compaction）全部只在内存。**重启 uvicorn = 她忘了所有聊过的事**。对纪念向产品这是情感层面的缺陷：用户与她的对话就是纪念物本身。

## 改进方案

SQLite 单文件（如 `data/sessions.db`，路径进配置 `conversation` 节）：

1. 会话状态要能恢复**原文、逐条时间、滚动摘要和压缩边界**。可用 `sessions` + `messages` + `compactions`，但先写清 `seq`、压缩后删除/保留原文、时间前缀恢复规则；摘要与被压缩原文必须在同一事务里提交。
2. 以完成的轮次为写入单位，把用户输入、已确认保留的助手句子与摘要变更事务化。LLM 异常回滚不能留一条孤立用户消息；打断只写已开始播放的句子，按当前播放回执口径裁剪。若落盘失败，须把“本轮未持久化”明确告知并记录，不能静默继续宣称重启可恢复。
3. `get_session()` 未命中内存时查库重建；内存 LRU 只缓存空闲会话，不驱逐正在流式生成或播放回执尚未结算的状态。读写同一会话沿用现有锁，SQLite 操作离开事件循环；异步写入仍要等事务结果才能确认持久化成功。
4. `/api/reset` 在鉴权后删除消息、摘要和相关用户记忆，并清理内存态；重复 reset 应幂等。

不引入 ORM，标准库 `sqlite3` + `asyncio.to_thread` 足够；但同一会话的 chat、interrupt、playback 回执与 reset 有并发路径，仍须用事务和现有会话锁核对顺序。

## 验收

- `tests/test_web.py`：新建 app 并复用数据库后，历史、时间、摘要完整恢复；打断/异常/写入失败后的落库状态正确；reset 后库中无残留；另测跨会话读写与 reset 被拒绝。
- 端到端：重启 uvicorn，前端不换 session_id，她接得上重启前的话题（含超过 `recent_turns` 的部分走摘要恢复）。

## 边界与风险

- **隐私**：库只落本地盘；README 与配置注释说明位置、备份与清除方法。SQLite 若启用 WAL，还须一并处理 `-wal`/`-shm` 文件；通过应用内删除后无法保证覆写历史磁盘块。
- 与 P1-7（长期记忆）共享同一个 SQLite 文件，建表分开，便于一起迁移。
- **访问控制**：`session_id` 是客户端可指定的定位符，不是秘密凭据。会话数据落盘前，chat、playback、interrupt、reset 必须统一绑定到已验证的会话身份；只保护 reset 或使用默认关闭的可选 token，仍允许读取或改写他人历史。若只支持单用户本机使用，需强制回环地址并明确不提供局域网多用户隔离。

## 规模

M（新存储模块 + web.py 接线 + memory.py 重组逻辑适配 + 测试）。
