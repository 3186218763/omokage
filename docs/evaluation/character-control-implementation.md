# Kev + LLM 联合控制：交付与验收记录

日期：2026-09-23。实现对应[设计方案](../kev-llm-character-control-plan.md)。

## 已落地

- WebChatService 单循环调度 token、按序 TTS、首句 Kev 和 interrupt；Kev 完成立即交付，生成完成时取消未完成的辅助判定。TTS 预取有界，取消时回收任务。
- JevClient 复用连接池，整个调用有时间预算，忙时回落；校验 emotion/intensity 各自置信度，拒绝 NaN/非法值；本地来源标记 kev。日志只记录原因与总耗时，不打印密钥或对话。
- 浏览器请求 v2，所有 SSE 事件带 turn_id；sentence 内带 index/motion，performance 带 revision。未请求 v2 的旧调用保留原事件结构。
- PlaybackDirector 管理生成与播放生命周期：done 后继续播队列，拒播无动作，暂停按音频时钟冻结，短句缩短/跳过动作，迟到事件不跨轮，惊讶回落只使用本轮底色。
- 音频按待播顺序消费，独立播放实例隔离旧回调；失败推进下一条，暂停后从原位置继续。gain 后采样 RMS，淡出与口型同源。
- Live2D 使用 renderer 返回的真实参数范围，缺参不写；底色平滑、动作按媒体时间叠加、嘴部最终覆盖。关闭重复 runtime 口型；fallback 补眨眼，因为 renderer 已禁用内建眨眼。
- `/api/playback` 接收单调序号的 started/ended 回执；interrupt 携带精确 started_indices，避免浏览器解码失败的句子误入历史。SSE done 后仍可裁剪最后回复；旧 turn 的回执和取消无效。历史按已起播的整句保留，不宣称精确到字。
- 浏览器提供 `window.omokagePlaybackSamples()` 导出有界、无台词的本地诊断数据；Kev 60 条平衡场景评测脚本已提供。

## 验证记录

- 后端全量 pytest：339 项通过；随后新增的精确起播索引测试及最后修改涉及的后端测试共 45 项也已通过。
- 前端 Vitest：11 项通过，覆盖播放状态、音频队列、两条渲染路径、模型限幅和协议校验。
- Chromium 三项集成测试通过：真实 WAV 连播到结束、首次拒播后点击恢复、新轮取消旧队列及精确回执。
- `npm run build` 通过。仍有现存的大 bundle 提示；未将打包优化混入控制逻辑。
- [Kev 本机 60 条数据](kev-local-2026-09-23.json)：接受 50/60，符合预设合理标签 49/50；客户端总耗时 P50 210ms、P95 232ms。预设标签由工程样本给出，未经人工盲标，不是独立准确率证明。未用此留出集调门槛，维持 0.4。
- [真实链路单轮烟测](live-smoke-2026-09-23.json)：使用本机 Kev/TTS、配置中的 LLM 和 Hiyori 模型，无 pageerror。单轮不是性能分布或表演质量验收。

## 复现

在仓库根目录：

```bash
.venv/bin/python -m pytest -q
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m frontend.web --port 8011
```

另一个终端执行浏览器测试（首次安装浏览器用 `cd frontend && npx playwright install chromium`）：

```bash
cd frontend
npm run test:browser
OMOKAGE_URL=http://127.0.0.1:8011 node browser-tests/live-smoke.mjs
```

已有 Chromium 时，可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指定其绝对路径。测试配置不固定本机路径。烟测会调用真实 LLM/TTS；确定性测试使用 fixture，不访问模型。

Kev 评测：

```bash
.venv/bin/python -m scripts.eval_character_control --output docs/evaluation/kev-local.json
```

浏览器控制台导出 `JSON.stringify(window.omokagePlaybackSamples())` 保存为 JSON 后：

```bash
.venv/bin/python -m scripts.eval_character_control --browser-log playback.json --output playback-summary.json
```

## 尚未完成的人工/设备验收

1. 日常、沉重、玩笑各 20 轮的录屏盲测，以及真实合成声线听感评审。
2. 同机交错开/关 Kev 各至少 60 轮，比较首音 P95；当前只有 Kev 单独请求延迟与真实链路烟测。
3. 声卡回环测量可听起点、打断后实际静音时间。`playing` 是浏览器事件，不等同硬件声卡时间。
4. 发丝等物理响应：现有 renderer 自定义写入发生于 physics 后，本版保证绘制合成，未引入未经验证的 physics 前私有挂点。

配置仍用 `jev` 段。本地无认证 Kev 可使用 `api_key: local`；禁用 `jev.enabled` 后自动用说话语气底色。当前 SBV2 仍为锁定声线，本次未声称增加六种可控声学 style。运行服务的模型 revision 未由接口暴露，评测报告记录 checkout 和本机缓存 revision，不能把它当成已验证的服务端权重证明。
