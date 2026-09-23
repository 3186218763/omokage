# P0-5 音频下行编码瘦身（base64 WAV → 有损压缩）

## 差距（airi 怎么做）

airi 的 TTS 音频走独立通道（官方流式 TTS 是双向 WebSocket 会话，`airi/packages/stage-ui/src/libs/speech/tts-session.ts`），文本与控制走事件总线——音频从不塞进 JSON 文本通道。

## 我们的现状

`frontend/web.py` 的 SSE 事件 `{"type":"audio","audio":<base64 WAV>}`：WAV PCM 原始字节 + base64 文本化，合计比裸 PCM 膨胀约 33%；按 44.1kHz/16bit 单声道算一条 5 秒句子约 440KB，而同样内容 MP3/Opus 128kbps 只要 ~80KB。对 SSE 单连接来说，这既是带宽也是首音下发延迟（要先把整个 base64 帧吐完）。

## 改进方案（两档，先 A 后 B）

**A 档（改编码，协议不动，先做）**：

1. 服务端合成事件里把 WAV 转码为单声道 MP3（`ffmpeg -ac 1 -b:a 96k`，subprocess，包在 TTS task 里——与 P0-1 叠加时转码在 task 内做，不占流水线主线程）。兼容性最好，浏览器 `HTMLAudioElement` 全支持；`useAudioQueue.ts` 用的是 audio 元素 + WebAudio 图，RMS 口型取的是 analyser，与容器格式无关。
2. SSE 事件结构不变（仍 base64），体积先降 ~80%。

**B 档（换通道，协议动，后做）**：音频事件改为 `{"type":"audio","url":"/api/audio/{turn}/{index}"}`，前端按序 fetch 二进制流——去掉 base64、获得 HTTP 缓存与浏览器原生解码。依赖 P0-1 的预合成（音频在播放时点之前已就绪，fetch 无额外等待）。

## 验收

- A 档：同一条回复的 audio 事件总字节数对比（目标 -75% 以上）；听感盲测无劣化（MP3 96k 单声道对语音足够）；打断淡出（gain ramp）行为不变。
- B 档（若做）：句序播放不变、打断时丢弃未 fetch 的 URL、无乱序。

## 边界与风险

- 转码引入 ffmpeg 部署依赖：`scripts/setup_sbv2.sh` 环境本就有 ffmpeg；纯 Python 兜底可用 `lameenc`（无外部二进制）。
- MP3 编码有 ~20-50ms 首尾 padding，句子间可能引入极轻的静音差——对连续播放无感，验收里口头带过即可。
- 不改 SBV2 服务端输出（WAV 是它锁声线 API 的稳定契约），转码在我们这侧做。

## 规模

A 档 S；B 档 M（前端 `api/client.ts` 与 `useAudioQueue.ts` 的取数路径改动）。
