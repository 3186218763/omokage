# P2-11 她主动开口（spark 轻量版）——需产品决策

## 差距（airi 怎么做）

airi 把「自主意识」降维成一个小而干净的机制（值得学的是这个降维手法，不是它的规模）：

- `spark:notify` 事件协议（`airi/packages/plugin-protocol/src/types/events.ts`）：`kind: alarm|ping|reminder` × `urgency: immediate|soon|later`，任何模块都能发起「有事值得她知道」；
- 2 秒 tick 的注意力调度器（`airi/packages/stage-ui/src/stores/character/orchestrator/store.ts`）：immediate 立即处理，soon/later 延迟 10s/60s，失败退避重试；
- **由 LLM 自己决定回应还是沉默**（`airi/packages/core-agent/src/agents/spark-notify/agent.ts`，含显式 `sparkNoResponse` 工具），prompt 一句值得抄的话："This is the life pod hosting your consciousness. You do not need to respond to every event."

## 我们的现状

纯被动应答：她永远不会先开口。对纪念向产品，主动性的情感价值极高（久别的一句「好久不见」），但也最危险（打扰感、幽灵推送感、与「不复活承诺」的边界）。

## 为什么是 P2

与 CONTEXT.md 的现约定有张力：「前端只暴露实时对话这一种交互」。她主动开口**不新增 UI 入口**（仍是对话里的一条消息），但改变了「一轮由用户发起」的交互模型，属于产品级决策，不是工程优化。前置依赖：P0-3（持久化，判断「多久没来」）与 P1-8（时间感知，判断「到晚安时间了」）。

## 若做的最小方案（决策通过后）

1. **只做三个触发器**，全部「用户在场」为前提（她不对着空气说话）：
   - 久别重逢：会话恢复时距上次对话 ≥48h → 开场白带时间感（「好几天没见啦」）；
   - 晚安：当天对话活跃过、且用户在配置的时间窗（如 23:00 后）仍在线 → 至多一次/天；
   - 用户主动设的约定提醒（「明天提醒我」）：依赖 P1-7 记忆的「约定」kind。
2. **决策权给 LLM，协议抄 airi**：触发器只产出候选（kind + urgency + 上下文摘要），是否开口、说什么由一个轻量 LLM 调用决定，显式支持「不开口」；人格与红线沿用现有 system prompt，不另写人设。
3. **频率硬闸**：每天至多 1-2 次、每会话冷却 4h、配置总开关（默认关）——工程闸优先于模型自觉。
4. 前端形态：主动消息走同一条 SSE 句子事件 + TTS 合成（服务端主动推，需把现在的「请求驱动」流改为可由服务端发起；这是本方向主要的工程量）。

## 验收（若做）

- 三触发器各一组正反例（该开/不该开）；频率闸不可被绕过；总开关关闭时零主动消息。
- 盲测：主动消息的语气与在场感同对话轮无差别；无「定时推送感」。

## 不做

airi 的完整注意力循环、任意模块 spark 注入、跨端通知——我们要的是「她会先说话」，不是一套事件系统。

## 规模

M（决策后：触发器 + 服务端主动推送通道 + LLM 决策调用 + 频率闸）。
