# 改进方向（对标 airi 研究结论）

本目录是 2026-09 对标 [moeru-ai/airi](https://github.com/moeru-ai/airi)（`595ea72`，v0.12.0-beta.5）后的改进提案。各篇最初写于实现之前，正文的「差距」保留当时背景；是否还能直接领走，以本索引及各篇开头的状态说明为准。

参考仓库本地克隆在 `/home/mtr/tt/airi`（浅克隆）；文中 `airi/...` 路径均指该仓库，本文档引用行号以 `595ea72` 为准。

2026-09-24 按各篇「改进方案」对照当前工作树核对。方案已经写进代码的五篇在 [done/](done/README.md)。下表只留还缺功能或协议的提案。未提交改动不等于已进入 `master`。代码已接线不等于体验达标。云端 LLM 生成人格化台词，Kev/Jev（System One）判表演情绪，Style-Bert-VITS2 锁定声线合成。

## 还没做完

| # | 方向 | 已经有的 | 还缺 |
|---|------|----------|------|
| P0-3 | [会话持久化](p0-03-session-persistence.md) | 本地基础版：SQLite 存消息、逐条时间和摘要；`/api/history` 恢复，`/api/reset` 删除；落盘开启时 CLI 只听回环地址 | 读写仍是同步 `sqlite3`，没有离开事件循环；非本机部署没有鉴权；设备级重启验收未做 |
| P0-5 | [音频下行编码瘦身](p0-05-audio-downlink-encoding.md) | A 档可选：`streaming.audio_encoding: mp3` 时 TTS task 用 ffmpeg 转码，SSE 带 `mime_type`，没有 ffmpeg 就回落 WAV。默认仍是 WAV | B 档短时 URL 未做；体积、首音、句间和听感未在目标设备上测 |
| P1-6 | [口型：元音驱动与交还协议](p1-06-lipsync-vowel-and-handoff.md) | 正常结束后约 200ms smoothstep 收口；打断沿音量淡出清口型。开合仍是浏览器 RMS → `ParamMouthOpenY` | 元音嘴形未启用，也还没有目标声线的标注样本 |
| P1-7 | [用户长期记忆](p1-07-long-term-user-memory.md) | 默认关闭。启用后只从「我叫 / 我的名字是 / 我喜欢 / 我不喜欢」抽字面短事实，时间衰减排序，可看来源、逐条删除，清空会话时一并删 | 没有 LLM 抽取、向量检索、手动纠错，也没有「新说法否定旧说法」的 superseded |
| P1-9 | [空闲 idle 动画层](p1-09-idle-motion-layer.md) | Soullink runtime idle 已启用。没有 runtime 时，`blendParams()` 有身体微摆和眨眼 | 方案里的 `ParamBreath`、独立重心周期、视线换点都还没写；要不要加，先看录屏 |
| P1-10 | [每轮时延观测](p1-10-turn-latency-observability.md) | `232b7c6` 的服务端 `TurnTiming` 与 `timing` SSE。本地又有浏览器 `playing` / `ended` / `performance_applied` 采样 | 可听句间静音没有稳定汇总。`p0_verify.py` 打印的仍是服务端 `audio_gaps_ms` |
| P2-11 | [她主动开口](p2-11-proactive-spark.md) | 无 | 产品边界未定，触发器与服务端主动推送都未写 |
| P2-13 | [人设资产卡片化](p2-13-persona-card.md) | 花音卡片能校验并供给 `get_system_prompt()`；`scripts/check_character_card.py` 可单独跑 | 运行时不按卡片换声线；没有第二人物，也没有 CCv3 兼容 |

P0-4 的两个 CI job 已经落地，见 [done/](done/README.md)。后加的前端 vitest / Playwright 要不要进 workflow，仍是未决后续，不另开一篇。

## 依赖关系

- P2-11（主动开口）前置：P0-3（持久化，判断「久别」）。时间感知已在 [done/P1-8](done/p1-08-time-awareness.md)，它只提供日期和消息时间，不提供在线状态或定时触发。
- [P0-1](done/p0-01-tts-prefetch-pipeline.md)、[P0-2](done/p0-02-jev-early-dispatch.md) 的设备体验验收，需要在 P1-10 的服务端打点之外，用浏览器播放事件算可听间隔和起播前覆盖率。
- P1-7 的跨重启验收依赖 P0-3；P2-11 的「约定提醒」还依赖 P1-7。
- P1-6 与 P1-9 都会写 Live2D 参数，实施时须核对同一参数的所有权。

## 明确不学（与定位冲突）

airi 是通用「AI 虚拟角色容器」平台，以下能力是它的生存负担而非我们的差距：

- **多平台集成**（Discord/Telegram/Minecraft/VSCode/Twitter）：单角色纪念向没有多端在场需求。
- **三层插件生态**（plugin-protocol/plugin-sdk/远程模块 + 权限模型）：没有第三方开发者，维护面扩大十倍。
- **通用 provider 抽象**（LLM/STT/TTS）：当前核心是云端 LLM + Kev/Jev + SBV2 锁声线，没有为多供应方框架付出复杂度的需求。
- **LLM 跑浏览器 / WebGPU 推理**：与核心架构相反。
- **桌宠多窗口（Electron 15 种窗口）/ 移动端**：产品形态是 Web 舞台一种。
- **多人 server-runtime / 云同步 / 计费网关**：本地单用户。

另一面，我们有两块 airi 完全没有对应物的护城河，改进不应稀释它们：**从 B 站素材到 SBV2 微调的克隆声线数据管线**（人声分离→声纹过滤→共识 ASR→一致性校验→记分卡门禁），以及**盲测一票否决的验收体系**（文本/听感/交互/表演四轨）。
