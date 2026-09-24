# Kev + LLM 联合控制人物：实现资料核验

调研日期：2026-09-23。本文给架构方案提供一手依据；**读过源码 / 上游报告**与**本项目建议 / 待实测项**分别标注，不把上游基准当成本机保证。遵守 `CONTEXT.md` 与 ADR-0001：LLM 管说话语气、句级动作；System One 管持续表演情绪。当前 TTS 实际能力以项目代码为准，本文不推导“表演情绪会改变声线”。

## 1. 固定版本与资料边界

| 项目 | 本次核验版本 | 阅读位置 |
| --- | --- | --- |
| Kev | `557598fced1dada75dfbf36ed144dce309ac6ceb` | [README][K1]、[API 转换][K2]、[服务实现][K3] |
| AIRI（当前仓库 moeru-ai/airi） | `595ea7260d95d25a654572cfdd52e96cb9441290` | [语音管线][A1]、[播放管理器][A2]、[Stage 接线][A3] |
| pixi-live2d-display 上游 | `31317b37d5e22955a44d5b11f37f421e94a11269` | [Cubism4InternalModel][P1] |

以上 commit 通过 GitHub `git ls-remote ... HEAD` 核验，源码通过克隆或相同 commit 的现有本地 checkout 阅读。没有实际下载 Kev 权重、运行推理或测本项目端到端延迟。pixi 这一版是**上游参照**，不代表本项目 Soullink renderer 包内恰好使用同一实现；实际渲染钩子必须检查安装版本。

## 2. Kev 真正做什么

**源码已验证：** Kev 是文本状态上的闭集决策模型；`POST /v1/systemone` 接收 `state`、`model`、`questions`。`state` 可为字符串或 JSON，对象/数组会被转换成带字段名的文本。`choice` 问题的 `criteria` 是 1–255 项的名称到描述的映射，输出 `choice`、`confidence`、`probabilities`；它不直接生成台词、音频、Live2D 曲线，也不是音频情绪识别器。[K1][K2]

适合本项目的请求形状（**方案示例，不是已运行结果**）：

```json
{
  "model": "kev-latest",
  "state": {
    "user_utterance": "最近真的有些累。",
    "assistant_speaking_style": "gentle",
    "assistant_first_sentence": "那就先慢慢来呀。"
  },
  "questions": {
    "emotion": {
      "type": "choice",
      "instructions": "Choose the assistant's restrained visible performance for this response, not the user's emotion. Serious topics should be gentle. Do not choose crying or sadness.",
      "criteria": {
        "casual": "Ordinary relaxed conversation",
        "energetic": "Bright energetic presence",
        "gentle": "Soft reassuring presence",
        "playful": "Light teasing or joking",
        "defiant": "Mild assertive resistance, never aggression",
        "surprised": "Brief visible surprise"
      }
    }
  }
}
```

示例使用现有 adapter 的 emotion 标签名，须映射回本项目六类中文闭集；实际请求同时加入现有 intensity 问题。第一句早派发是减少等待的**本项目设计选择**，上游不替你决定派发时机。不要把原本基于整轮文本的判定描述成“已经看完本轮台词”。

### 置信度不是正确率

`kev/api.py` 明确实现：[K2]

```text
choice confidence = (max(probabilities) - 1/K) / (1 - 1/K)
```

六类时，`confidence=0.4` 相当于 `p_max=0.5`，`confidence=0.6` 相当于 `p_max≈0.667`。既不能把 `confidence` 当 `p_max`，也不能把它当“这个判断有 60% 正确率”。`score` confidence 使用另一套按等级距离计算的公式，不能混用。API 只将统计量四舍五入到四位小数。[K2]

**上游报告：** 默认温度校准来自其自身开发集，README 明确要求在自己的数据上检验阈值，且选项顺序可能影响答案；提供 `/v1/systemone/permute` 辅助检查。[K1][K3] 这没有证明对本项目中文台词、俏皮/倔强等六类仍然校准良好。

**建议：** adapter 保留原始 `confidence`、`probabilities` 和 provider/model/revision；初版用可配置阈值，拿本项目三场景语料评估误接受、回落比例、选项顺序敏感性后再定。低置信度回落到 LLM 说话语气，不在线改成自由发挥的表情。

### 延迟与并发的实际边界

以下是 **README 上游报告，不是本机实测**。[K1]

| 条件 | 请求条件 | 上游数字 |
| --- | --- | --- |
| Kev-4B / NVIDIA L4 / bf16 | 三问，101-token 请求，20 请求/行 | 118 ms |
| Kev-4B / NVIDIA L4 / bf16 | 三问，330-token 请求，20 请求/行 | 189 ms |
| Kev-0.8B / Apple M5 32 GB / MLX | 约 270-token state，五问、每问三选项；直接模型中位数 | 新 state 149 ms；重复 state 28 ms |
| Kev-4B / Apple M5 32 GB / MLX | 同上 | 新 state 721 ms；重复 state 136 ms |

不能用“几十毫秒”作为默认用户体验预算：硬件、模型、状态长度和缓存条件都不同。前缀缓存以完整 state token 序列为 key，每轮文本变化不保证命中。[K3]

**更关键的源码细节：** `Server.probs()` 用一把 `threading.Lock` 串行推理，在**取得锁以后**才启动 `latency_ms` 的计时。因此响应里的这个数字不包含等待这把锁的时间，也不代表完整 HTTP 往返；服务不跨请求合批。[K3] 客户端应以 monotonic clock 单独记录端到端耗时，并限制待处理数量；超时回落不代表 GPU 上已开始的推理必然被取消。

**部署建议：** 第一阶段按单会话服务；Kev 超时不能阻塞 TTS 首包或播放；记录冷启动、热启动、并发情况下的 P50/P95 和显存。模型权重与代码分别固定 revision，不能仅记 `kev-latest`。服务默认监听 localhost、无需认证，可设 `KEV_API_KEY`；项目现有 `JevClient.configured` 要求非空 key，无认证的本地服务可沿用 `configs/config.example.yaml` 中的 `api_key: local`；若启用服务认证，则必须配置实际匹配的 key。现有客户端还按 `emotion`/`intensity` 两个答案读取，并将 emotion confidence 交给 `from_jev_choice` 门槛；Kev adapter 需要明确字段映射，不能只改 URL。[K1][项目客户端](../dialogue/jev_client.py)

## 3. AIRI 值得借鉴的是播放生命周期，不是照抄标签语义

**源码已验证：** AIRI 的 speech pipeline 区分文本分段、并发 TTS 完成、按序调度、播放 start/end/interrupt/reject，使用 `turnId`、`intentId`、`streamId`、`segmentId` 关联；取消同时检查标志与 AbortSignal。[A1] 本项目可采用较小版本：`turn_id + sentence_id + playback lifecycle`，无需搬入整个跨窗口总线和 intent 优先级系统。

**容易误读的细节：** `enqueuePlayback()` 在 `await waitForPlayback(item)` 之后才派发附在该 item 的 special，waiter 由播放终止事件 resolve。因此它不是通用的“句首动作”实现；独立 special 则是时间线另一项。[A1] 不能看到 AIRI 支持 special token 就断言它默认把动作精确对齐句首。

此外 AIRI playback-manager 的 `onStart` 在调用 `options.play()` **之前**发出，`startedAt` 使用 `Date.now()`，并非天然等同于声卡已发声或 Web Audio 精确起点。[A2] 本项目应该把动作启动绑到自己的音频后端实际启动回调；若提前 `AudioBufferSourceNode.start(when)` 排程，则记录 `AudioContext.currentTime` 同一时钟上的 `when`，明确允许的音画误差。

**建议：** 句级动作由 LLM 标签解析后与句子一起入队，等该句音频开始才触发；音频失败则不播放对应句的说话动作。打断废弃旧 turn 的音频、动作和迟到 Kev 结果；端到端验收应包含 TTS 乱序完成、播放拒绝、音频解码失败和旧轮迟到回调，不能只测正常路径。

## 4. Live2D 叠加顺序要查真实渲染循环

**上游源码已验证：** `Cubism4InternalModel.update()` 顺序是：[P1]

```text
beforeMotionUpdate
→ motionManager.update
→ afterMotionUpdate
→ saveParameters
→ expressionManager.update
→（无 motion 更新时）eyeBlink
→ focus
→ breath
→ physics
→ pose
→ beforeModelUpdate
→ coreModel.update
→ loadParameters
```

由此可知，随意在独立定时器里 `setParameterValueById()` 可能被后续层覆盖；每帧覆盖也不等于持续状态，因为最后会恢复保存的参数。`beforeModelUpdate` 位于 physics 后面，能影响最终绘制，却不会再让当帧 physics 对新姿态做计算。这是具体版本的实现事实，不能把“最后写入”说成“所有物理也自动正确”。[P1]

**建议：** 保留现有 Soullink 引擎，用一个明确的 renderer adapter 作为自定义参数写入口。表演情绪提供底色，动作提供有限持续时间的增量，口型保留自己的嘴部参数，眼神/眨眼/呼吸各自限定写集合。使用实际模型的 min/max clamp，缺参数跳过，避免默认假定任意 Cubism 4 模型都有同一套可动参数。涉及头部/身体的动作若要驱动物理，需核验 renderer 暴露的 physics 前钩子；没有合适钩子时应承认第一版只保证绘制叠加，并以录屏评估。

不要在引擎外另建第二个每帧 loop 与现有 engine 争写，也不要让 Kev 按帧输出参数。逐帧曲线、抢占、节流和恢复由本地确定性逻辑完成；Kev 与 LLM 都只交付低频语义意图。

## 5. 对方案的直接约束

1. 先解决句子和音频的身份关联、真实播放时钟、打断失效，再提高表情丰富度；否则联合控制只会更明显地暴露不同步。
2. Kev 作为可失败的表演情绪建议源；LLM 持有句级语义动作。低置信度、异常、过期一律回落，不阻塞首句音频。
3. 把“何时锁定本轮表演情绪”写成明确策略。早派发只看首句，晚派发看整轮但可能错过播放；这是真实取舍，上游不会自动解决。
4. 已有说话语气、表演情绪和动作词表优先复用。不要顺带引入新的声线控制、全双工或任意动作生成。
5. 在实际硬件与中文评测集上测量，才能确定模型大小、timeout 和 confidence 门槛；上游数字仅用于安排试验。

[K1]: https://github.com/jaredpalmer/kev/blob/557598fced1dada75dfbf36ed144dce309ac6ceb/README.md
[K2]: https://github.com/jaredpalmer/kev/blob/557598fced1dada75dfbf36ed144dce309ac6ceb/kev/api.py
[K3]: https://github.com/jaredpalmer/kev/blob/557598fced1dada75dfbf36ed144dce309ac6ceb/kev/serve.py
[A1]: https://github.com/moeru-ai/airi/blob/595ea7260d95d25a654572cfdd52e96cb9441290/packages/pipelines-audio/src/speech-pipeline.ts
[A2]: https://github.com/moeru-ai/airi/blob/595ea7260d95d25a654572cfdd52e96cb9441290/packages/pipelines-audio/src/managers/playback-manager.ts
[A3]: https://github.com/moeru-ai/airi/blob/595ea7260d95d25a654572cfdd52e96cb9441290/packages/stage-ui/src/components/scenes/Stage.vue
[P1]: https://github.com/guansss/pixi-live2d-display/blob/31317b37d5e22955a44d5b11f37f421e94a11269/src/cubism4/Cubism4InternalModel.ts
