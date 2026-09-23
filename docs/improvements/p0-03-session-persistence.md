# P0-3 会话持久化（内存 LRU → SQLite 落盘）

## 差距（airi 怎么做）

airi 的会话历史持久化在浏览器 IndexedDB（`airi/packages/stage-ui/src/database/storage.ts`，unstorage + indexeddb driver），配套云同步的 outbox/tombstone 对账（`repos/chat-sessions.repo.ts`）。云同步我们不学，但「历史与摘要不因进程重启丢失」是它的底线。

## 我们的现状

`frontend/web.py` 的 `get_session()`：会话是进程内 dict，上限 128、LRU 剔空闲；对话历史与滚动压缩摘要（`dialogue/memory.py` 的 compaction）全部只在内存。**重启 uvicorn = 她忘了所有聊过的事**。对纪念向产品这是情感层面的缺陷：用户与她的对话就是纪念物本身。

## 改进方案

SQLite 单文件（如 `data/sessions.db`，路径进配置 `conversation` 节）：

1. 三张表：`sessions(session_id, created_at, last_active)`、`messages(session_id, seq, role, content, created_at)`、`compactions(session_id, seq_from, seq_to, summary)`——摘要单独存，不与原文混放，`prepare_chat_messages` 重组时按 seq 拼接。
2. 写入时机：沿用现有 `conversation.add_*` 调用点，提交语义不变（打断的半截回复、异常回滚都照 web.py:268-270 的 `committed` 逻辑落库）；落库失败不阻断对话（降级为纯内存，记日志）。
3. 读取时机：`get_session()` 未命中内存时查库重建；内存 LRU 上限照旧（内存只是缓存，不再是真的存储）。
4. `/api/reset` 对应 DELETE；顺带把「session_id 客户端可任意指定」带来的越权面收窄（见风险）。

不引入 ORM，标准库 `sqlite3` + `asyncio.to_thread` 足够；单用户写入频率极低，无并发问题。

## 验收

- `tests/test_web.py`：重启模拟（新建 WebChatService 实例、同一 session_id）后历史与摘要完整恢复；打断轮、异常轮的落库状态正确；reset 后库中无残留。
- 端到端：重启 uvicorn，前端不换 session_id，她接得上重启前的话题（含超过 `recent_turns` 的部分走摘要恢复）。

## 边界与风险

- **隐私**：纪念向对话数据敏感，库只落本地盘，绝不上云（也不为未来云同步预留字段）；README 与配置注释里写明数据位置与清除方法（删文件即清除）。
- 与 P1-7（长期记忆）共享同一个 SQLite 文件，建表分开，便于一起迁移。
- 会话鉴权缺失（任何人可 POST 任意 session_id 操作他人会话）是既有事实，本方向至少做到「落盘数据不因未鉴权被第三方 reset 清掉」——reset 加可选 token 配置，默认本地模式不强制。

## 规模

M（新存储模块 + web.py 接线 + memory.py 重组逻辑适配 + 测试）。
