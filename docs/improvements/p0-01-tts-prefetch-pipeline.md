# P0-1 TTS 句间流水线并行（合成深度 1 → 2-3，按序下发）

## 差距（airi 怎么做）

airi 的语音管线核心在 `airi/packages/pipelines-audio/src/speech-pipeline.ts`：LLM token 流 → 分句 → **并发 TTS（默认 4 路）+ 序号保序调度** → 播放时间线。配套 intent 语义（`queue | interrupt | replace` + priority），打断就是管线级取消。它把「上一句合成完才开始下一句」这个浪费彻底消掉了。

## 我们的现状

`frontend/web.py:160-175` 的 `emit_sentence`：产出第 N+1 句的事件前，必须先 `yield await self._audio_event(pending_audio)`（web.py:168-169）把第 N 句音频完整合成并下发，然后才 `create_task` 第 N+1 句的 TTS（web.py:173）。**合成流水线深度恒为 1**：用户听第 N 句时，第 N+1 句还没开始合成，句间存在「下发 → 起合成 → 合成完」的空等。句子越短、轮次越长，空隙越密集，直接拖累「像实时语音聊天」的验收。

CLI 路径（`dialogue/orchestrator.py` 的 tts_queue/audio_queue 双 worker）反而是队列式的，Web 路径是历史遗留的串行化。

## 改进方案

把 `pending_audio`（单个 task）改成**深度可配的按序队列**（建议默认 2，配置进 `streaming` 节，键如 `tts_prefetch_depth`）：

1. `emit_sentence` 不再先结清上一句：直接为当前句 `create_task` TTS，句序推进时若队列深度未满就继续；音频事件仍严格按句序 yield（保序下发不变）。**协议注记（实现时确立）**：audio/audio_error 事件带 `index`（轮内句序）——预取下音频可能晚于后续 sentence 事件到达，前端动作配对从「暂存到下一块到达的音频」改为 motion→句 index→音频 index（`useChat.ts`），`useAudioQueue` 本体不动。
2. 打断（让路）时取消**所有**在飞 TTS：`_cancel_task(pending_audio)` 的调用点扩展为逐个取消队列；断连（GeneratorExit/aclose）与异常路径经外层 `finally` 兜底取消，预取队列不产生孤儿任务。ADR 0002 的语义不变——已 yield 的句子照常进历史，未播出的丢弃。
3. 深度上限尊重 SBV2 单卡现实：默认 2、上限 3（`config.MAX_TTS_PREFETCH_DEPTH`），配置即逃生门——设 1 即回退旧行为，不需要运行时自动降级（TTS 故障以逐句 `audio_error` 呈现，与深度无关）。

不引入 airi 的完整 intent/priority 管线——我们只有一种打断语义，一个按序小队列就够。

## 验收

- `tests/test_web.py`：多句回复的事件顺序不变（sentence/audio 交错次序、句序、音频序号）；打断用例扩展为「队列里 2-3 个在飞 TTS 全部取消、无孤儿任务告警」。
- 端到端：用 P1-10 的时延观测对比改动前后**句间 gap p95**，应显著下降；首音延迟不劣化。
- 语义回归：打断后历史仍是「已送出的 sentence 事件」近似（web.py:253-259）。

## 边界与风险

- SSE 事件流是生成器串联，改并发要小心 yield 顺序；保序由队列结构保证，不由协程调度运气保证。
- SBV2 服务端（`scripts/run_sbv2_api.py`）是否欢迎并发请求需实测；不行就在客户端限制深度为 2 并留配置逃生门。
- 与 P0-5（音频编码瘦身）叠加时注意：转码如果是同步的，会把预合成赚的时间吐回去，转码也要进 task。

## 规模

S-M（web.py 局部重构 + 测试扩展；CLI 路径不动）。
