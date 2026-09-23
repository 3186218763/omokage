# P1-9 空闲 idle 动画层：呼吸、重心、视线的低幅度常动

## 差距（airi 怎么做）

airi 不让皮套静止：motion 管理器是 pre/post/final 三段插件管线（`airi/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts`），插着 IdleDisable/IdleFocus、BreathControl、AutoEyeBlink（有状态缓动相位、multiply 调制）等层。进阶版 MAGIC（`airi/packages/motion-driver-magic`）用 AR-HMM 拟合录制动作数据生成无限不重复 idle——思路可取，重量不取。

## 我们的现状

`frontend/src/live2d/stage.ts`：不说话、无动作时，舞台回落到**静态的**表演情绪底色（`blend.ts` 的情绪→VAD 参数混合），身体与视线没有持续微动。真人（和像真人的皮套）没有完全静止的时刻——静态底色是「纸片感」的主要来源。已有的 `MOTION_CURVES` 程序化曲线机制（点头/摇头/歪头）证明这条技术路线可行，只是还没用于 idle。

## 改进方案

在现有分层（表演情绪底色 → 句级动作叠加）**下面**加一层持续 idle：

1. **三条低幅度程序化曲线随机叠加**（全部只用 Cubism 标准参数，维持任意 Cubism 4 皮套可跑）：
   - 呼吸：`ParamBreath`（无此参数的模型退化为 `ParamBodyAngleY` ±1-2°），周期 3-5s 正弦；
   - 重心：`ParamBodyAngleX/Z` ±1-3°，周期 8-15s，与呼吸不同相位；
   - 视线漂移：`ParamEyeBallX/Y` ±0.1-0.2，每 4-10s 换一个注视目标点，缓动过去。
2. **实现挂点**：复用 `MOTION_CURVES` 的曲线驱动，在 stage 的渲染 tick 里以「乘性/加性低权重」合成，排在表演情绪混合**之前**（idle 是底色的底色，情绪重、动作更重，层级不被倒挂）。
3. **省电与克制**：幅度刻意压低（远小于情绪混合的幅度），节流 30fps 以内；说话与动作期间不抑制（低幅度叠加不冲突），无需状态机。

不做：MAGIC 式统计模型（需要录制数据集与拟合管线，收益不抵成本）、眨眼（若皮套自带 idle motion 有眨眼，避免双驱动——先检查占位模型表现再定，眨眼作为独立小项后补）。

## 验收

- 表演轨录屏盲测：静止 30 秒无「纸片感」（有持续生命感）、微动不喧宾夺主（不干扰正在进行的对话表演）。
- 资产兼容：在无 `ParamBreath`/少参数的极简 Cubism 4 模型上不报错、优雅退化。

## 边界与风险

- 与占位皮套自带 idle motion 的叠加冲突：以程序化层为准或可配置关掉资产 idle（`resources/live2d/README.md` 的资产约定里注明）。
- 幅度参数需要盲测调 2-3 轮，预留前端 debug 页（`frontend/debug.html`）加幅度滑杆。

## 规模

M（曲线组 + 合成次序 + debug 滑杆 + 盲测调参）。
