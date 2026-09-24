# 已实现

2026-09-24 对照当前工作树核对后移入。标准是各篇「改进方案」已经写进代码：配置、调用点和对应测试能对上。设备测量、盲测、评测回归可以仍开放，不把代码落地当成体验达标。`232b7c6` 已在 `master`；标成「本地未提交」的还在工作树里。

| # | 方向 | 代码 | 仍开放 |
|---|------|------|--------|
| P0-1 | [TTS 句间流水线并行](p0-01-tts-prefetch-pipeline.md) | `232b7c6`：`tts_prefetch_depth` 默认 2、上限 3，音频带 `index`，打断取消在飞合成 | 浏览器 `ended → next playing` 的句间静音；SBV2 单卡并发 |
| P0-2 | [Jev/Kev 提前发起](p0-02-jev-early-dispatch.md) | 本地未提交：首句派发、等待中交付、流结束取消；输入标明为未完成前缀 | 中文首句/全文对照、起播前覆盖率、设备验收 |
| P0-4 | [CI](p0-04-ci-github-actions.md) | `232b7c6`：`.github/workflows/ci.yml` 跑 `pytest` 与 `tsc --noEmit` | 后加的 vitest / Playwright 要不要进 workflow，仍未决 |
| P1-8 | [时间感知](p1-08-time-awareness.md) | `232b7c6`：日期锚点、`[HH:MM]` 只在组 prompt 时加、摘要带时间 | 真实会话的跨天表达；既有人设盲测 |
| P2-12 | [台词停顿标签](p2-12-speech-pause-token.md) | 本地未提交：气口只放在后一句前；第一句不空等；单条重听立刻播；失败句不插静音 | 听感盲测 |

未完成的提案仍在 [上一级目录](../README.md)。
