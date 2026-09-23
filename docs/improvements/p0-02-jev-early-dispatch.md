# P0-2 Jev 表演情绪提前发起（流尾才问 → 首句就问）

## 差距（airi 怎么做）

airi 的表演控制是**流内即时**的：`airi/packages/pipelines-audio/src/llm-streaming-control/` 从流式 token 里解析 `<|ACT {"emotion":...,"motion":...}|>` 控制事件，与 TTS 分句同序投递——情绪/动作在播放到那一句之前就已经到位。

## 我们的现状

职责划分不同（ADR 0001：动作/说话语气由 LLM 标签先行，表演情绪由 System One 判定），这点不改。问题在**发起时机**：

- `frontend/web.py:226-230`：`jev_task` 在 LLM 流完全结束、尾句全部 flush 之后才 `create_task`。
- `frontend/web.py:234-239`：await 与最后一句音频并行，覆盖事件在 `add_assistant_message` 之后、`done` 之前才 yield（web.py:263-267）。

结果是：整轮流式输出期间，前端一直用「说话语气兜底」的表演情绪（web.py:155-158 先发一个 fallback performance 事件），Jev 的真实判定最多覆盖到还在播的尾部几句。而 2 秒超时（`dialogue/jev_client.py`）完全来得及在 LLM 还在流式输出时就返回。

## 改进方案

**改 Jev 的输入协议：允许部分文本。** `JevClient.ask_messages` 现在收 `(history, normalized_response 完整回复)`；情绪判定其实主要依据用户最新消息与对话走向（`performance.build_jev_state()` 本来就末尾强调用户最新一句），不需要等完整回复：

1. 首句产出时（说话语气标签解析完成后）即发起：输入 = history + 首句（或前两句）文本。
2. 流尾只 await（现有 web.py:234-239 的收口逻辑不变），覆盖事件语义不变——仍是「后到的 performance 覆盖先前的兜底」。
3. Jev 不可用/超时/低置信的行为完全不变（回落说话语气、60s 失败冷却）。

改完的时序：首句 TTS 在合成时，Jev 大概率已在 2s 内返回 → 覆盖事件在第二轮句子播放前就到 → **表演情绪几乎整轮生效**，而不是只覆盖尾巴。

## 验收

- `tests/test_jev_client.py`：新增部分文本输入用例（首句输入与完整回复输入映射一致或差异可解释）。
- `tests/test_web.py`：jev_task 的创建时点在首句事件之后、流结束之前；打断时 jev_task 照常取消（web.py:244-249 路径不回退）。
- 端到端：P1-10 观测里记录 jev_dispatch → jev_done 与首句播放的时间关系，覆盖事件到达早于「流结束」。

## 边界与风险

- **首句判错的风险**：首句文本短，情绪信息可能不足。缓解：Jev 输入里用户最新消息权重最高（现状如此），且 fallback 链路完整——判不出来就还是说话语气兜底，不会更差。
- 不改成 airi 的「LLM 流内 ACT token」方案：那会把表演情绪判定权交回 LLM，违反 CONTEXT.md 的控制归属约定（表演情绪归 System One）。
- 若未来 Kev（本地）时延降到百毫秒级，本方向收益进一步放大，方案不变。

## 规模

S（`dialogue/jev_client.py` 输入放宽 + web.py 发起点上移 + 测试）。
