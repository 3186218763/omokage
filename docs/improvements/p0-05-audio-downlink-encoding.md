# P0-5 音频下行编码瘦身（base64 WAV → 有损压缩）

**状态（2026-09-23，本地工作树）：A 档已做成可选能力，默认仍用 WAV。** 设 `streaming.audio_encoding: mp3` 后，TTS task 用 ffmpeg 转码，SSE 带 `mime_type`，前端按实际类型播放；ffmpeg 不存在时回落 WAV。B 档独立 URL 尚未做；MP3 的体积、首音、句间和听感仍需目标设备测量。

## 差距（airi 怎么做）

airi 的 TTS 音频走独立通道（官方流式 TTS 是双向 WebSocket 会话，`airi/packages/stage-ui/src/libs/speech/tts-session.ts`），文本与控制走事件总线——音频从不塞进 JSON 文本通道。

## 我们的现状

`frontend/web.py` 的 SSE 事件 `{"type":"audio","audio":<base64 WAV>}`：base64 相对 WAV 字节约增加 33%；若音频确为 44.1kHz/16bit 单声道，5 秒 PCM 约 441KB，128kbps 编码约 80KB。实际 SBV2 输出采样率、通道数、压缩率及端到端首音收益需测。现有前端收到完整 audio 事件后才解码与播放，慢链路上体积会影响等待，但编码和解码也有成本。

## 改进方案（两档，先 A 后 B）

**A 档（改编码，协议不动，先做）**：

1. 在 TTS task 中异步转码 WAV 为单声道 MP3（如 96kbps），并在事件里明确 `mime_type`，前端按实际类型创建 Blob URL；不能只换字节却仍标成 `audio/wav`。先用目标浏览器验证解码、播放、RMS 口型和打断淡出。
2. SSE 的 `audio` 类型和 base64 字段保留，增加真实 MIME 标识；以实际事件总字节数验证收益，目标压缩率仅作为验收假设。

**B 档（换通道，协议动，后做）**：音频事件改为指向短时有效的同源 URL，前端按句序取二进制；需定义会话授权、URL 生命周期、清理、取消及缓存头。额外 fetch 可能增加延迟，是否优于 A 档须实测。

## 验收

- A 档：同一条回复的 audio 事件总字节数对比（目标 -75% 以上）；目标设备听感盲测、句间静音和首音延迟不劣化；打断淡出（gain ramp）行为不变。
- B 档（若做）：句序播放不变、打断时丢弃未 fetch 的 URL、无乱序。

## 边界与风险

- 转码引入 ffmpeg 部署依赖：`scripts/setup_sbv2.sh` 环境本就有 ffmpeg；纯 Python 兜底可用 `lameenc`（无外部二进制）。
- MP3 编码器/解码器可能引入首尾 padding；多句连续播放的可听间隙须实测，不能预设「无感」。
- 不改 SBV2 服务端输出（WAV 是它锁声线 API 的稳定契约），转码在我们这侧做。

## 规模

A 档 S；B 档 M（前端 `api/client.ts` 与 `useAudioQueue.ts` 的取数路径改动）。
