# P1-10 每轮时延观测：把「像实时聊天」变成数字

**状态（2026-09-23）：已在 `232b7c6` 落地服务端打点与 `timing` SSE。** `frontend/turn_timing.py` 记录 TTFT、首句、每次音频下发、Jev 派发/完成和轮末；尚无浏览器实际起播与可听句间静音的稳定汇总口径。新增浏览器播放 telemetry 的本地改动仍需单独验收。

## 差距（airi 怎么做）

airi 的可观测性相当重：context 9 相生命周期追踪 + prompt projection 快照（`airi/packages/stage-ui/src/stores/devtools/context-observability.ts`）、WebSocket inspector、OTel span（TTFT、chunk 统计）。我们不要 OTel 依赖，但要它的态度：**体感由时延数字定义，不靠感觉**。

## 我们的现状

实施前这些节点没有结构化记录。现在 `TurnTiming` 已记录服务端时间线，但服务端的 `audio_sent` 间隔不等于浏览器实际播放的句间空白；完整体验指标仍需前端同一时钟上的播放事件。

## 改进方案

1. **每轮时间线**：`frontend/web.py` 的 `stream()` 里在关键节点打时间戳（`time.perf_counter()`）：
   `request → llm_first_token → first_sentence → first_audio_sent → 每句 audio_sent → jev_dispatch / jev_done → done`。
2. **两种出口**：
   - 服务端：`logs/timing.jsonl` 每轮一条 JSON，含句数、打断标记和相对时延；当前 payload **不含**会话 id、轮 id，且只有预先存在 `logs/` 时才装载文件 handler。
   - SSE：终态事件前可发 `{"type":"timing", ...}`（`conversation.timing_event` 默认开）；协议客户端会校验事件，页面没有时延条。
3. **当前口径**：`first_audio_ms` = 服务端开始计时到首个成功 audio 下发；`audio_gaps_ms` = 相邻成功 audio 下发时间差，未扣除前一句时长，不能称为可听「句间 gap」；Jev 决策时延 = `jev_done_ms - jev_dispatch_ms`，前提是两个值都存在。
4. **待补体验口径**：同一浏览器时钟记 `playing/ended`，可听句间静音为上一句 ended 到下一句 playing 的时差；起播前覆盖率以 performance 实际应用时间早于首句 playing 计算。`p0_verify.py --timing` 已有无播放的服务端摘要，但其中「句间gap」打印的是 `audio_gaps_ms`，不能当作听感指标。

## 验收

- 单测：时间线事件完整性与单调性；打断轮的 timing 缺省字段语义（jev 未发起则空）。
- 服务端时间线可比较 P0-1 的音频下发间隔与 P0-2 的判定耗时；真实句间静音和起播前覆盖率须另用浏览器播放事件计算。

## 边界与风险

- 不引 OTel/metrics 栈：单用户部署，JSON 日志 + jq 就能查；复杂度留给真需要的时候。
- `timing` 已进入 `api/client.ts` 的闭集类型校验；以后新增事件类型仍须同批更新客户端，不能假定未知事件会被忽略。

## 规模

S（1 天内，含 p0_verify 扩展）。
