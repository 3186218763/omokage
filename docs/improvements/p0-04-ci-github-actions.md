# P0-4 CI：把 268 个测试接进 GitHub Actions

## 差距（airi 怎么做）

airi 有完整的 CI 底盘：turbo 任务图 + vitest（含浏览器模式测试）+ 多阶段流水线，`pnpm test:run` 一条命令全跑。我们不需要它的规模，需要它的**底线**：合入前测试必须自动跑过。

## 我们的现状

- 35 个测试文件、268 个测试函数，全部 mock、不依赖外部服务（测试 README 明示）——**却没有任何 CI**（仓库无 `.github/` 目录）。
- 前端构建含 `tsc --noEmit` 类型检查，同样只在本地手动跑。
- Python 侧无 lint/ruff 配置。

测试资产已经是现成的，缺的只是一条 workflow。

## 改进方案

一个 `.github/workflows/ci.yml`，两个 job：

1. **backend**：`ubuntu-latest` × Python 3.11——`pip install -e '.[web]'` + `pytest`（`asyncio_mode=auto` 已配好，全 mock 无外部依赖，天然可跑）。
2. **frontend**：`ubuntu-latest` × Node 20——`cd frontend && npm ci && npx tsc --noEmit`（暂不跑 `vite build`，按需再加）。

触发：push 到 master + PR。缓存 pip 与 npm 依赖。

不做（明确出界）：覆盖率门禁、多 Python 版本矩阵、前端单测（目前没有）、Lint 全面接入——这些等有真实痛再上，避免 CI 变成负担。

## 验收

- PR 上两个 job 绿；本地 `pytest` 与 CI 结果一致。
- 故意推一个失败测试验证会红（一次性验证，不留在历史）。

## 边界与风险

- 私有仓库的 Actions 分钟数消耗极小（两个轻量 job）。
- 若仓库含子模块或需要 SBV2/LLM 外部服务的测试，维持现状不接入——CI 只跑 mock 测试，正好与现有测试设计一致。

## 规模

S（半天内，含验证）。
