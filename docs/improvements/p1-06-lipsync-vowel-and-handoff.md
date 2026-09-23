# P1-6 口型升级：元音驱动 + 说话结束交还协议

## 差距（airi 怎么做）

airi 的 Live2D 口型是两层设计（`airi/packages/model-driver-lipsync/src/live2d/index.ts` + `airi/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts`）：

1. **元音驱动**：wLipSync AudioWorklet 从播放音频实时提取 AEIOUS 六元音权重 + 音量；映射时 S→I 重映射、幅度乘 `volume^0.7` 压低、上限 0.7、40ms 节流（≈25fps）、120ms 窗口插值——口型形状随元音变化，不是单纯张嘴大小。
2. **交还协议**：说完话后 200ms smoothstep 把 `ParamMouthOpenY` 交还给 idle 动画曲线，再**强制闭嘴 500ms**（handoff hold）——防止 idle 曲线在交还瞬间把嘴重新拉开，产生「说完话嘴又莫名张开」的破功。

## 我们的现状

`frontend/src/hooks/useAudioQueue.ts`：WebAudio analyser 取 RMS → `stage.setMouth()` 写 `ParamMouthOpenY`。只有「开合度」一个维度，元音形状（ParamMouthForm）没有；说话结束没有交还协议，嘴型从 RMS 值直接掉回，与 idle/表演层的参数衔接靠自然衰减，偶发跳变。

## 改进方案

分两步，第二步独立可先做（更便宜、破功收益更大）：

1. **元音驱动（M）**：在 `useAudioQueue` 的 WebAudio 图里加 AudioWorklet 做轻量元音分析。不直接搬 wLipSync WASM（额外依赖与许可核对），先用两三个共振峰频带能量（如 F1≈低频段 270-730Hz、F2≈中频段 840-2410Hz 的能量比）把 a/i/u 三元音粗分，映射 `ParamMouthOpenY`（开合）+ `ParamMouthForm`（嘴形，a≈大开口、i≈扁宽、u≈收圆）；保留 RMS 做开合底量。RMS 平滑逻辑保留。
2. **交还协议（S）**：`useAudioQueue` 检测一条音频播完 → 200ms smoothstep 把口型值过渡到舞台当前值 → 强制 0 保持 500ms → 交还。打断淡出路径（gain ramp ~200ms）复用同一收口。

参数只用 `ParamMouthOpenY`/`ParamMouthForm` 两个 Cubism 标准参数，维持「任意 Cubism 4 皮套可跑」的约束；缺 `ParamMouthForm` 的模型自动退化为纯开合。

## 验收

- 表演验收轨（CONTEXT.md 验收第 4 轨）加一条：说话口型录屏盲测——元音与嘴形对得上（说「你好啊」嘴不只是一个开合量）、说完不出现嘴型回弹/突跳。
- `useAudioQueue` 单测：交还协议的状态机（speaking → releasing → hold → idle）与打断路径。

## 边界与风险

- 频带能量法对 SBV2 合成音（干净人声、无伴奏）足够；不需要 wLipSync 级别的精度。
- 口型跟「正在播放的合成音」是 CONTEXT.md 明文约定，本方向只是把跟随做得更像，不改变数据源。

## 规模

交还协议 S；元音驱动 M（AudioWorklet + 映射调参 + 盲测）。
