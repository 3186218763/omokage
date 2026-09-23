# 改进方向（对标 airi 研究结论）

本目录是 2026-09 对标 [moeru-ai/airi](https://github.com/moeru-ai/airi)（`595ea72`，v0.12.0-beta.5）后的差距分析落成的改进提案。每个方向一份 md，互不依赖，可独立领走。

参考仓库本地克隆在 `/home/mtr/tt/airi`（浅克隆）；文中 `airi/...` 路径均指该仓库，本文档引用行号以 `595ea72` 为准。

前提共识：**保持本项目核心不动**——云端 LLM 生成人格化台词、Kev/Jev（System One）判表演情绪、Style-Bert-VITS2 锁定声线合成。airi 学的是它打磨最狠的两层（语音管线、Live2D 驱动）与工程底盘，不学它的平台化包袱。

## 优先级索引

| # | 方向 | 档位 | 一句话 | 规模 |
|---|------|------|--------|------|
| P0-1 | [TTS 句间流水线并行](p0-01-tts-prefetch-pipeline.md) | 直接收益 | 合成深度 1→2-3，句间不再空等 | S-M |
| P0-2 | [Jev 提前发起](p0-02-jev-early-dispatch.md) | 直接收益 | 流尾才问 → 首句就问，表演情绪覆盖整轮 | S |
| P0-3 | [会话持久化](p0-03-session-persistence.md) | 直接收益 | 内存 LRU → SQLite 落盘，重启不失忆 | M |
| P0-4 | [CI](p0-04-ci-github-actions.md) | 工程底线 | 268 个测试接进 GitHub Actions | S |
| P0-5 | [音频下行编码瘦身](p0-05-audio-downlink-encoding.md) | 直接收益 | base64 WAV → 有损压缩，带宽 -80% 以上 | S-M |
| P1-6 | [口型：元音驱动与交还协议](p1-06-lipsync-vowel-and-handoff.md) | 体感升级 | RMS 张嘴 → 元音口型 + 说完不回弹 | M |
| P1-7 | [用户长期记忆](p1-07-long-term-user-memory.md) | 体感升级 | 遗忘曲线检索的「她记得你」 | M-L |
| P1-8 | [时间感知](p1-08-time-awareness.md) | 体感升级 | 她知道今天几号、现在几点 | S |
| P1-9 | [空闲 idle 动画层](p1-09-idle-motion-layer.md) | 体感升级 | 静止底色 → 呼吸/重心/视线微动 | M |
| P1-10 | [每轮时延观测](p1-10-turn-latency-observability.md) | 体感升级 | TTFT/首音/句间 gap 数字化 | S |
| P2-11 | [她主动开口（spark 轻量版）](p2-11-proactive-spark.md) | 方向性 | 久别问候/晚安，需产品决策 | M |
| P2-12 | [台词停顿标签](p2-12-speech-pause-token.md) | 方向性 | 【停顿:短】，台词有呼吸感 | S-M |
| P2-13 | [人设资产卡片化](p2-13-persona-card.md) | 方向性 | 为「复刻下一位」铺路的资产格式 | M |

## 依赖关系

- P2-11（主动开口）前置：P0-3（持久化，判断「久别」）、P1-8（时间感知，判断「晚安」）。
- P0-1、P0-2 的验收量化依赖 P1-10，但实现不阻塞。
- 其余方向相互独立。

## 明确不学（与定位冲突）

airi 是通用「AI 虚拟角色容器」平台，以下能力是它的生存负担而非我们的差距：

- **多平台集成**（Discord/Telegram/Minecraft/VSCode/Twitter）：单角色纪念向没有多端在场需求。
- **三层插件生态**（plugin-protocol/plugin-sdk/远程模块 + 权限模型）：没有第三方开发者，维护面扩大十倍。
- **47 家 provider 抽象**（LLM/STT/TTS）：我们的核心就是「云端 LLM + 本地 Kev + SBV2 锁声线」，一个 provider 都不换。
- **LLM 跑浏览器 / WebGPU 推理**：与核心架构相反。
- **桌宠多窗口（Electron 15 种窗口）/ 移动端**：产品形态是 Web 舞台一种。
- **多人 server-runtime / 云同步 / 计费网关**：本地单用户。

另一面，我们有两块 airi 完全没有对应物的护城河，改进不应稀释它们：**从 B 站素材到 SBV2 微调的克隆声线数据管线**（人声分离→声纹过滤→共识 ASR→一致性校验→记分卡门禁），以及**盲测一票否决的验收体系**（文本/听感/交互/表演四轨）。
