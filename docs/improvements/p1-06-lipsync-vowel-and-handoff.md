# P1-6 口型升级：元音驱动 + 说话结束交还协议

**状态（2026-09-23，本地工作树）：结束收口过渡已接线，元音嘴形未启用。** 浏览器 analyser 的 RMS 仍驱动 `ParamMouthOpenY`；正常播放结束后约 200ms 平滑收口，打断沿现有音量淡出路径清理。元音分析需要目标声线标注样本和录屏验证，不能直接套用其他人的校准 profile。

## 差距（airi 怎么做）

airi 的 Live2D 口型是两层设计（`airi/packages/model-driver-lipsync/src/live2d/index.ts` + `airi/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts`）：

1. **元音驱动**：wLipSync AudioWorklet 从播放音频实时提取 AEIOUS 六元音权重 + 音量；映射时 S→I 重映射、幅度乘 `volume^0.7` 压低、上限 0.7、40ms 节流（≈25fps）、120ms 窗口插值——口型形状随元音变化，不是单纯张嘴大小。
2. **交还协议**：说完话后 200ms smoothstep 把 `ParamMouthOpenY` 交还给 idle 动画曲线，再**强制闭嘴 500ms**（handoff hold）——防止 idle 曲线在交还瞬间把嘴重新拉开，产生「说完话嘴又莫名张开」的破功。

## 我们的现状

`frontend/src/hooks/useAudioQueue.ts`：WebAudio analyser 取 RMS → `stage.setMouth()` 写 `ParamMouthOpenY`。外部口型只有开合度，`ParamMouthForm` 仍由表演底色决定；结束时 `onRms(0)`，未定义外部驱动与 idle/表演层的交还状态。是否出现可见跳变需录屏核实。

## 改进方案

分两步，第二步独立可先做（更便宜、破功收益更大）：

1. **元音驱动（M，先试验）**：先用 SBV2 生成中日文覆盖 a/i/u/e/o 的短句，标注音素时间并录屏，比较现有 RMS、轻量频带特征和经过许可核对的成熟口型识别方案。只有轻量方案在真实音频与模型上稳定区分嘴形时才接入 AudioWorklet；保留 RMS 开合兜底，缺 `ParamMouthForm` 时仍只开合。
2. **交还协议（S）**：明确 `playing → releasing → idle` 状态，音频 `ended/error` 时从当前外部口型值平滑收口；打断期间与实际 gain 同步收口。是否需要额外 hold 由目标模型录屏决定，避免与 Soullink 内建 idle 同时争写嘴部参数。

参数只用 `ParamMouthOpenY`/`ParamMouthForm` 两个 Cubism 标准参数，维持「任意 Cubism 4 皮套可跑」的约束；缺 `ParamMouthForm` 的模型自动退化为纯开合。

## 验收

- 表演验收轨加一条：同一句音频的 RMS 基线与候选口型方案并排盲测，检查音画同步、元音形状与结束回弹；缺参数模型须优雅降级。
- `useAudioQueue` 单测：结束、暂停、播放拒绝和打断时的口型所有权与状态转换。

## 边界与风险

- 频带能量能反映谱形，但共振峰位置随说话人、音高、音素和上下文变化；是否足够必须由带时间标注的样本和录屏验证。
- 口型跟「正在播放的合成音」是 CONTEXT.md 明文约定，本方向只是把跟随做得更像，不改变数据源。

## 规模

交还协议 S；元音驱动 M（AudioWorklet + 映射调参 + 盲测）。
