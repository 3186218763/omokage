# P1-9 空闲 idle 动画层：呼吸、重心、视线的低幅度常动

**状态（2026-09-23）：已有部分能力，待资产录屏验收。** `stage.ts` 启用 Soullink runtime 的 idle；fallback `blendParams()` 也有随时间变化的低幅参数。是否需要额外呼吸或视线曲线，须先看实际模型参数、渲染更新顺序和录屏结果。

## 差距（airi 怎么做）

airi 不让皮套静止：motion 管理器是 pre/post/final 三段插件管线（`airi/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts`），插着 IdleDisable/IdleFocus、BreathControl、AutoEyeBlink（有状态缓动相位、multiply 调制）等层。进阶版 MAGIC（`airi/packages/motion-driver-magic`）用 AR-HMM 拟合录制动作数据生成无限不重复 idle——思路可取，重量不取。

## 我们的现状

旧提案把现状写成静态底色；当前 `stage.ts` 的 Soullink idle 已启用，`blend.ts` fallback 也有微动。实际表现取决于模型提供的参数及 renderer 是否保留这些写入，不能只凭代码断言舞台静止或已经自然。

## 改进方案

若录屏证实还有明显静止，再在现有分层（表演情绪底色 → 句级动作叠加）中补缺失的 idle 维度：

1. **三条低幅度程序化曲线随机叠加**（全部只用 Cubism 标准参数，维持任意 Cubism 4 皮套可跑）：
   - 呼吸：`ParamBreath`（无此参数的模型退化为 `ParamBodyAngleY` ±1-2°），周期 3-5s 正弦；
   - 重心：`ParamBodyAngleX/Z` ±1-3°，周期 8-15s，与呼吸不同相位；
   - 视线漂移：`ParamEyeBallX/Y` ±0.1-0.2，每 4-10s 换一个注视目标点，缓动过去。
2. **实现挂点**：先核对已安装 renderer 的帧更新顺序与 Soullink 参数输出，再在现有 `stage.ts` 合成路径里加缺失维度；同一参数只留一个写入方，并按模型 min/max 限幅。
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
