# P1-10 每轮时延观测：把「像实时聊天」变成数字

## 差距（airi 怎么做）

airi 的可观测性相当重：context 9 相生命周期追踪 + prompt projection 快照（`airi/packages/stage-ui/src/stores/devtools/context-observability.ts`）、WebSocket inspector、OTel span（TTFT、chunk 统计）。我们不要 OTel 依赖，但要它的态度：**体感由时延数字定义，不靠感觉**。

## 我们的现状

一轮对话里的关键时延——首 token（TTFT）、首句产出、首音下发（首音延迟）、句间 gap、Jev 决策时延——全部没有结构化记录。`scripts/p0_verify.py` 只验证链路通不通。后果：P0-1/P0-2 这类改进无法量化验收，「感觉快了」不能作为依据；线上（哪怕单用户）退化也无从发现。

## 改进方案

1. **每轮时间线**：`frontend/web.py` 的 `stream()` 里在关键节点打时间戳（`time.perf_counter()`）：
   `request → llm_first_token → first_sentence → first_audio_sent → 每句 audio_sent → jev_dispatch / jev_done → done`。
2. **两种出口**：
   - 服务端：一轮结束打一条结构化 JSON 日志（现有 `logs/` 目录），含会话 id、轮 id、句数、打断标记与上面全链路时延；
   - SSE：`done` 事件前附一个 `{"type":"timing", ...}` 事件（配置开关 `conversation.timing_event`，默认开）——前端 debug 页直接显示本轮时延条。
3. **汇总口径**（写在本文档，作为团队语言）：首音延迟 = request → first_audio_sent；句间 gap p95 = 相邻 audio_sent 与上一句播放时长的差值分布（前端上报可选，先用服务端近似：相邻 audio_sent 间隔 - 该句标称时长）；Jev 决策时延 = jev_dispatch → jev_done（注：P0-2 落地前 Jev 在流尾才发起，「覆盖早于播放」恒不成立，该指标先看决策本身耗时，P0-2 后再升级为覆盖率）。
4. `p0_verify.py` 扩展：跑一轮真实链路后输出上述时延一行摘要，作为改进前后的对比基准。

## 验收

- 单测：时间线事件完整性与单调性；打断轮的 timing 缺省字段语义（jev 未发起则空）。
- 用它给 P0-1（句间 gap）与 P0-2（Jev 覆盖率）各出一份改动前后对比数字。

## 边界与风险

- 不引 OTel/metrics 栈：单用户部署，JSON 日志 + jq 就能查；复杂度留给真需要的时候。
- timing 事件对前端是新增事件类型，`api/client.ts` 的类型守卫要同步（向后兼容：未知事件忽略）。

## 规模

S（1 天内，含 p0_verify 扩展）。
