# omokage

虚拟人物重现：把一个人的台词、声线与在场表演合成可对话的纪念向 AI。
当前重现的是虚拟歌手 **真白花音（ましろ・はな）**。输入文字（或语音），
云端 LLM 生成花音风格的台词，本地 Style-Bert-VITS2 以花音音色合成语音并播放。
项目同时包含从 B 站素材采集到说话人微调的数据管线；声线引擎已从 GPT-SoVITS 切到 Style-Bert-VITS2。

## 功能特性

- **Live2D 舞台**：整页只有模型。她的台词在底部对话框里按正在说的那一句弹出，语音同步播放；左上角「记录」打开这一段对话。口型跟正在播放的合成音，表演情绪先跟说话语气，本地 Kev（或托管 Jev）返回后再覆盖。决策题是英文，映射回中文闭集。缺模型时占位为「菜」。资产说明见 [`resources/live2d/README.md`](resources/live2d/README.md)
- **句级动作**：LLM 按闭集（点头/摇头/歪头）在句前自标 `【动作:点头】` 一类标签（不朗读、不进 UI、不进历史），前端在对应句起幅做程序化动作，叠加在表演情绪底色上；动作可在同一轮按句重复，服务端按句绑定并清洗
- **打断（让路）**：她说话时点麦克风开口或点舞台，当前语音 ~200ms 淡出、本轮剩余合成与生成停止；已说出的句子照常进对话历史（她说过的算说过），与断连回滚是两种语义
- **流式语音对话**：LLM 边生成、TTS 边合成、喇叭边播放，asyncio 三段流水线并行，首音延迟低
- **长对话记忆**：最近 `recent_turns` 轮保留原文，更早历史滚动压缩为 LLM 摘要，可支撑数百轮对话
- **本机会话恢复**：Web 对话与摘要默认保存在 `data/sessions.db`，重启后恢复文本记录；「记录」面板可单独启用用户自述记忆并逐条删除，清空会话会同时删除记忆。落盘模式仅供本机访问
- **自然语音切分**：按句末标点 / 逗号 / 空格切句，保护括号动作与引用
- **CLI 与 Web 双前端**：CLI 本地播放；Web（React + TypeScript）是整页 Live2D，SSE 流式台词进对话框，默认 WAV，可选 MP3 下行，浏览器录音（faster-whisper 本地转写）
- **训练数据管线**：白名单采集 → 人声分离 → 静音切分 → 歌声/能量过滤 → 声纹过滤 → ASR 转写 → 音文一致性校验，全阶段增量断点续跑
- **无头训练**：导出 `dataset_precision` 为 Style-Bert-VITS2 布局后微调（resample → 文本 → BERT/style → train_ms）
- **专属声音 API**：`POST /tts {"text": "你好"}` 永远是花音这一条声线，调用方不能换说话人

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # 对话核心（CLI 播放需要 libsndfile / PortAudio）
pip install -e '.[web]'     # 额外安装 FastAPI + uvicorn + faster-whisper
```

### 2. 配置

```bash
cp configs/config.example.yaml configs/config.yaml
# 编辑 configs/config.yaml：填入 LLM API key、模型与 Style-Bert-VITS2 API 地址
```

**TTS 配方：** [`configs/huayin_sbv2.yaml`](configs/huayin_sbv2.yaml)

运行时人设由 [`configs/huayin_card.yaml`](configs/huayin_card.yaml) 加载；修改 prompt 前先更新 [`docs/persona/persona-spec.md`](docs/persona/persona-spec.md)，可用 `python scripts/check_character_card.py` 验证引用资产。

### 3. 启动 Style-Bert-VITS2 TTS 服务

```bash
# 一次性安装 Style-Bert-VITS2 训练/推理环境（conda env: sbv2）
bash scripts/setup_sbv2.sh

# 先导出数据并完成微调，再启动锁定声线的 API
python scripts/export_sbv2_dataset.py
python scripts/train_sbv2.py
python scripts/run_sbv2_api.py --host 127.0.0.1 --port 5000
```

对外合成接口（说话人在服务端锁定，请求里多带的 speaker/style 会被忽略）：

```bash
curl -X POST http://127.0.0.1:5000/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好"}' \
  --output hello.wav
```

### 4. 对话

```bash
# CLI 模式（Ctrl+C 退出）
python -m frontend.cli

# Web 模式（先构建前端，再启动服务；浏览器打开 http://127.0.0.1:8000/，健康检查 /healthz）
cd frontend && npm install && npm run build
cd .. && python -m frontend.web --host 127.0.0.1 --port 8000
```

仅验证本地模型推理、不启动对话层：

```bash
python scripts/test_huayin_tts.py "你好，今天也要加油。"
```

Web 会话默认落在 `data/sessions.db`（不入库），在「记录」中清空会话会删除对应消息与用户记忆；如需纯内存模式，设 `conversation.database_path: ""`。使用 `streaming.audio_encoding: mp3` 需要 ffmpeg，缺失时自动回落 WAV。落盘模式的 CLI 只允许本机监听；局域网部署需先提供鉴权方案。

## 项目结构

```
├── config.py                    # 类型化配置加载（YAML → dataclass）
├── configs/config.example.yaml  # 配置模板（实际配置 config.yaml 被 gitignore）
├── dialogue/                    # 对话核心
│   ├── llm_client.py            # OpenAI Responses 流式客户端 + 摘要接口
│   ├── tts_client.py            # Style-Bert-VITS2 TTS API 客户端（只发 text）
│   ├── tts_api.py               # 锁定声线的 POST /tts FastAPI 应用
│   ├── asr_client.py            # 本地 faster-whisper 转写（懒加载）
│   ├── conversation.py          # 对话历史：近期原文 + 滚动摘要 + 原子压缩
│   ├── memory.py                # CLI/Web 共用的记忆压缩与上下文组装
│   ├── sentence_streamer.py     # token 流 → 自然边界句子切分
│   ├── orchestrator.py          # LLM→切句→TTS→播放 的 asyncio 流水线
│   ├── audio_player.py          # sounddevice 播放（桌面端可选依赖）
│   ├── persona.py               # 从花音角色卡加载 system prompt
│   └── speech_text.py           # 台词清洗：去 Markdown/括号动作/角色名前缀
├── frontend/
│   ├── src/                     # React + TypeScript 前端源码
│   ├── dist/                    # 构建产物（npm run build 生成，不入库）
│   ├── package.json / vite.config.ts / tsconfig.json
│   ├── cli.py                   # CLI 前端
│   └── web.py                   # FastAPI + SSE 对话服务（服务 dist/index.html）
├── scripts/                     # 数据管线 / 训练 / 运维脚本（见下表）
├── data/                        # 数据管线各阶段产物（见下）
├── model/                       # 训练好的模型权重（Git LFS）
└── tests/                       # pytest 测试（全部 mock，不依赖外部服务）
```

## 配置说明

| 配置节 | 关键项 | 说明 |
|--------|--------|------|
| `llm` | `api_key` / `base_url` / `model` | OpenAI Responses 接口（`/v1/responses`）；`temperature 0.8`、`max_tokens 400` 适合口语对话 |
| `tts` | `base_url` / `model_name` / `speaker_name` | Style-Bert-VITS2 锁定声线 API；客户端只发 `text`，说话人在服务端固定为花音 |
| `asr` | `model` / `device` / `compute_type` | 浏览器录音转写，默认 `small`，首次使用会下载模型 |
| `conversation` | `recent_turns` / `summary_trigger_turns` / `summary_trigger_chars` / `summary_max_chars` | 记忆分层阈值；旧配置 `max_turns` 仍作为 `recent_turns` 别名 |
| `streaming` | `min_sentence_chars` / `max_sentence_chars` | 切句边界，默认 4 / 50 字 |

## 对话机制

**记忆分层**：`Conversation` 保存最近 `recent_turns` 轮原文 + 较早历史的滚动摘要。
完整历史达到 `summary_trigger_turns` 轮或 `summary_trigger_chars` 字符时触发压缩：
先由 `plan_compaction()` 生成不可变压缩计划，摘要成功后 `apply_compaction()` 原子提交
（提交前校验历史未变，避免并发误删）。摘要失败则保留原文继续本轮，不影响主回复。
上下文顺序固定为：人设 system prompt → 记忆摘要（system）→ 近期原文 → 当前用户消息。

**句子切分**：`SentenceStreamer` 优先在句末标点切分；超过 `max_chars` 时在括号外的
逗号/顿号/空格处切；没有自然边界才切到硬上限，且不会从括号动作或引用中间硬切。

**流水线**：`Orchestrator.chat()` 中 LLM 流式输出 → 切句 → `tts_queue` 合成（失败只跳过
该句音频）→ `audio_queue` 顺序播放；LLM 异常时回滚当前用户消息。Web 端每个
`session_id` 有独立 `asyncio.Lock`，同一会话请求严格串行，SSE 事件类型：
`sentence`（含对应句的 `motion` 元数据）/ `audio`（base64 WAV）/ `performance` / `interrupted` / `done` / `error` / `audio_error`。
打断是独立信号（`POST /api/interrupt`），不抢会话锁：正在流式的一轮在句边界停下，
部分回复进历史；客户端断连仍整轮回滚。

## 数据管线

原始 WAV 放在 `data/wav/`，训练白名单在 `data/training_assets.txt`（逐行列出文件名）。
管线各阶段均支持增量断点续跑：

```
separate → slice → filter → speaker → asr → alignment → dataset
```

| 阶段 | 脚本 | 输入 → 输出 | 职责 |
|------|------|-------------|------|
| 采集 | `bili_download.py` / `batch_download.py` | B 站 → `data/wav/` | B 站 API 下载、搜索筛选、断点续传 |
| collect_plan | `build_collect_plan.py` | 搜索结果 → `data/collect_plan.json` | 中文优先分层（B 杂谈/中文 → A 切片 → C 长录播）与 shortfall 预估 |
| plan 下载 | `batch_download.py --from-plan` | plan → `data/raw`/`wav` | 按优先级下载；可 `--append-training-assets` |
| separate | `build_dataset.py --stage separate` / `run_parallel_separation.py` | `data/wav/` → `data/vocals/` | UVR5 BS-Roformer 人声分离，按白名单、长音频切块（默认 30 分钟）防内存溢出 |
| slice | `build_dataset.py --stage slice` | `data/vocals/` → `data/slices/` | 按 RMS 静音切分为短句，逐 vocal 增量 |
| filter | `build_dataset.py --stage filter` | `data/slices/` → `filter_results.json` | librosa `pyin` 音高特征：歌声（voiced_ratio / f0_cv / longest_voiced）、低能量、时长异常 |
| speaker | `filter_speakers.py` | 切片 + 声纹参考 → `speaker_results.json` | ECAPA-TDNN 声纹打分，剔除非花音人声 |
| asr | `build_dataset.py --stage asr` / `run_parallel_asr.py` | 保留切片 → `asr_results.json` | faster-whisper `large-v3` 增量转写 + 语种/置信度 |
| alignment | `verify_asr_alignment.py` | ASR 结果 → `alignment_results.json` | 强制语种二次转写，`SequenceMatcher` 校验音文一致性 |
| dataset | `build_dataset.py --stage dataset` | ASR + 对齐 → `data/dataset/` | 语种白名单（默认仅中日）、文本质量门、幻觉过滤，输出 `annotation.list`（对照集） |
| scorecard | `build_quality_scorecard.py` | 各阶段 JSON → `quality_scorecard.json` | 硬门 + 0–100 软分记分卡 |
| dataset_hq | `build_hq_dataset.py` | scorecard → `data/dataset_hq/` | ZH≥60% 配额出集、砍低质、单源 cap |
| validate_hq | `validate_hq_dataset.py` | `dataset_hq` → 验证报告 + 人听清单 | V1–V8 自动门禁 + 分层人听导出 |

一次全量重建：

```bash
python scripts/build_dataset.py --stage all
python scripts/verify_asr_alignment.py --gpus 0 1 --min-similarity 0.45
python scripts/build_dataset.py --stage dataset --require-alignment
```

文本质量门（`dataset_text_quality.py`）以确定性规则检查短语循环、字符狂奔、韩文污染、
拉丁字符占比过高等 Whisper 幻觉模式。`run_dataset_supervisor.py` 可监控分离完成后
自动跑完后续阶段；`dataset_progress.py` 输出各阶段规模统计。

## 训练（Style-Bert-VITS2）

保留的数据是 `data/dataset_precision/`（1179 条中文，约 1.25 小时）。导出为 SBV2 的 `raw/` + `esd.list` 后微调：

```bash
python scripts/export_sbv2_dataset.py
# 需要已安装的 Style-Bert-VITS2 仓库（python initialize.py --skip_default_models）
python scripts/train_sbv2.py --sbv2-root /home/mtr/tt/Style-Bert-VITS2
# 或后台: bash scripts/run_sbv2_train_tmux.sh start
```

推理资产写到 `Style-Bert-VITS2/model_assets/huayin/`（`config.json` + `*.safetensors` + `style_vectors.npy`）。
本仓库 `model/` 只保留参考音，不再放 GPT-SoVITS 权重。

## 脚本清单

| 脚本 | 职责 |
|------|------|
| `setup_sbv2.sh` | 创建 conda `sbv2` 环境并下载 BERT / 预训练权重 |
| `export_sbv2_dataset.py` | 把 `dataset_precision` 导出为 Style-Bert-VITS2 `raw/` + `esd.list` |
| `train_sbv2.py` / `run_sbv2_train_tmux.sh` | 无头预处理 + 微调 / tmux 启动 |
| `run_sbv2_api.py` | 锁定花音声线的 `POST /tts` 推理服务 |
| `test_huayin_tts.py` | 单条文本走 `/tts` 写 wav |
| `p0_verify.py` | 文字 → LLM → TTS → 播放 端到端链路验证 |
| `check_acceleration.py` | 检查当前环境可用的推理加速后端 |
| `build_dataset.py` | 数据管线主入口（各阶段可单独运行） |
| `run_parallel_separation.py` / `run_parallel_asr.py` | 多 GPU 并行分离 / 转写 |
| `filter_speakers.py` | 花音声纹参考构建与逐切片打分 |
| `verify_asr_alignment.py` | 强制语种二次 ASR 音文一致性校验 |
| `dataset_text_quality.py` | 确定性文本质量门（幻觉转写检测） |
| `run_dataset_supervisor.py` / `finish_quality_pipeline.py` | 分离后自动完成后续管线 / 声纹后自动收尾 |
| `dataset_progress.py` | 打印管线各阶段进度统计 |
| `batch_download.py` / `bili_download.py` | B 站搜索下载（API 绕过反爬） |
| `sync_training_assets.py` | 审计通过的候选素材加入训练白名单 |
| `audit_*.py` | ASR 质量 / 音频资产 / 切片时长 / 声纹结果审计 |

## 测试

```bash
python -m pytest -q
```

pytest 覆盖对话核心、切句、记忆压缩、流水线、Web SSE、锁定声线 `/tts`、配置加载与数据管线逻辑，
全部 mock 化，不依赖外部 API 或 GPU。

## 外部依赖说明

- 可选重依赖均为**懒加载**：`librosa`（filter 阶段）、`faster-whisper`（ASR / Web 录音）、
  `sounddevice` / `soundfile`（CLI 播放）、`audio_separator` 与 UVR5 权重（分离阶段），
  以及独立的 Style-Bert-VITS2 训练/推理环境，不安装也不会阻断其他命令。
- `data/` 仅跟踪 `training_assets.txt`；模型权重、数据集、中间产物均由 `.gitignore` 排除。
