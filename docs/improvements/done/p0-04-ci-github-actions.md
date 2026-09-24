# P0-4 CI：把测试接进 GitHub Actions

**状态（2026-09-24）：提案里的两个 job 已在 `232b7c6` 落地，本篇移入 `done/`。** `.github/workflows/ci.yml` 的 backend 跑 `pytest`，frontend 跑 `tsc --noEmit`。268 个测试是提案时快照，不是固定测试数。工作树里后加的 vitest 与 Playwright 仍未进 workflow，要不要纳入是未决后续，不是这篇首版还没写完。

## 差距（airi 怎么做）

airi 有完整的 CI 底盘：turbo 任务图 + vitest（含浏览器模式测试）+ 多阶段流水线，`pnpm test:run` 一条命令全跑。我们不需要它的规模，需要它的**底线**：合入前测试必须自动跑过。

## 我们的现状

- 提案时有 35 个测试文件、268 个测试函数；当时没有 CI。现在已有 GitHub Actions，测试数量随代码变化。
- 前端类型检查已经进入 CI；完整 `vite build` 与前端单测仍不在当前 workflow 中。
- Python 侧无 lint/ruff 配置。

首版 CI 已接线；新增前端测试后，测试命令仍需进入 workflow 才能形成合入门禁。

## 改进方案

一个 `.github/workflows/ci.yml`，两个 job：

1. **backend**：`ubuntu-latest` × Python 3.11——实际 workflow 使用 `pip install -e '.[dev,web]'` + `pytest`。
2. **frontend**：`ubuntu-latest` × Node 20——`cd frontend && npm ci && npx tsc --noEmit`（暂不跑 `vite build`，按需再加）。

触发：push 到 master + PR。缓存 pip 与 npm 依赖。

首版未接入覆盖率门禁、多 Python 版本矩阵或 lint。新增前端单测后，应明确决定是否在 frontend job 加 `npm run test`；浏览器测试需另备可启动的服务与资产，不能当作普通 typecheck 已覆盖。

## 验收

- PR 上两个 job 绿；本地 `pytest` 与 CI 结果一致。
- 前端单测接入后，增加一个只在测试环境运行的失败验证，确认 CI 真会阻止回归。

## 边界与风险

- 私有仓库的 Actions 分钟数消耗极小（两个轻量 job）。
- 若仓库含子模块或需要 SBV2/LLM 外部服务的测试，维持现状不接入——CI 只跑 mock 测试，正好与现有测试设计一致。

## 规模

S（半天内，含验证）。
