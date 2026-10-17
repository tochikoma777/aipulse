# 变更日志

本项目采用 [Keep a Changelog](https://keepachangelog.com/) 风格，按里程碑组织。
每个里程碑对应一个 git tag（`m0` … `m4`），并在 GitHub Releases 上发布。

**版本与 tag 的对应**：`m0`–`m4` 已发布；M4 之后的修复归入 `Unreleased`（随 M6a 一起发 `m5`）。
**设计文档版本**（见 `docs/AI_Pulse_设计方案.md` 头部的 `v1.x`）与代码版本**独立编号**，不要混淆。

---

## [Unreleased] — M4 之后的修复与 M6a

### [§5.14] star 追踪（今日 Trending vs 持续追踪）

> REA 掉榜诊断结案：**真掉榜，不是 bug**。但 `signals` 表一直在记 star 快照却从不展示，
> 导致"27 万 star、10 小时涨 8617"的项目因为掉榜就在日报里彻底消失。

#### Added

- **开源项目表格增加「★ 总数」「增量」两列**（紧跟「热度」）：数据来自 `signals` 表，
  **只显示绝对增量、不显示每小时速率**；`cold_start` / 无数据显示 `—`
- **「📈 增速榜（追踪中）」区块**：Top 5（`brief.velocity_board_top_n`），
  只纳入合规增速窗口（`status=ok`）且增量 > 0 的项目，排除今日已展示的；
  **0 条时整块不渲染**（`brief.velocity_board_enabled`，默认开）
- **`source_runs.json` 随日报落盘**：`source` / `status` / `item_count` / `started_at` /
  `finished_at` / `error`。下次"某项目怎么没了"不用连库，直接看报告
- `signals.repo_lookback_days`（默认 7）：star 增量只看最近 N 天，不混入更早的老快照

#### Changed

- star 增量取 **lookback 窗口内的首末快照**（与 `signals.json` 同口径），
  不是全表首末、也不是"最近两次"——同日多次运行会把最近两次压到 2 小时内，失去日报意义
- **增速榜改按日均增量排序**（`delta / hours × 24`）：窗口长度不同的绝对增量不可比
  （7 天涨 5000 会排在 1 天涨 3000 前面，但后者快 7 倍）。**显示仍是绝对增量 + 窗口**
  （`+8617 / 10h`），表格「增量」列同步带窗口标记

#### 统计

- 342 → 358 passed；新增 `repo_star_snapshots` / `velocity_board` 三态与 REA 用例

### [M6a] 格式规范化 + 快照型源修复 + 关注订阅

#### Fixed

- **★ predict_generate 降级为 0 条**：reasoner 输出撞 `max_tokens=4000` 被截断
  （实测 first_len=3442、retry_len=0）→ `llm.max_tokens_fast/strong` 分档（strong 8000），
  并把候选证据池收窄到 Top 20、只给 `id + 标题`（不再注入摘要）
- **同一 item 跨板块重复**：按源归一到主板块，Apple 不再同时出现在社区/产业
- **「要点」无摘要时重复标题**：改回 `—`，避免与第一列重复
- **★ 持续热门项目只出现一天就永久消失**：GitHub Trending 是**状态型源**（无发布时间，只有"此刻是否在榜"），
  却被当成事件型处理 → Item 增加 `last_seen_at`，`time_semantics` 按源类型选择过滤字段
- **★ 时间语义补第三态 `discovery`**：arXiv/HF 索引滞后 3-4 天，
  按 `published_at` 过滤会让 `lookback_days:7` 采来的论文全部丢失（**采了不用，白采**）
  → 改用 `first_seen_at`（读者关心"今天新发现了什么"，不是"投稿日期是不是今天"）
- 采集发生在窗口右界之后 → 采集后把右界推到 `utcnow()`

#### Added

- **「连续在榜 N 天」**（`trending_streak_days()`）：比单日热度更能说明一个项目是真火
- 简报格式规范化：头条带来源块 / 总览分条 / 点评拆四节带图标 / **表格列固定且空值占位**
- `brief.max_items_per_section`（默认 10）：超出显示「另有 N 条」
- Web 首页/归档同步同一套结构，兼容旧 `daily.json`

#### Changed

- 「一句话」列名改为「要点」（兼容 LLM 生成与摘要截断两种态）

#### 统计

- 319 → 342 passed，TOTAL 90%

---

## [Unreleased] — M4 之后的真实运行修复

> 这一节的共同点：**全部只有真实运行才暴露**。
> 本地桩测试全绿 ≠ 真实可用。这也是本项目最重要的经验。

### Fixed

- **Actions 首跑崩溃**：全新 clone 无 `data/` 目录，alembic 建库失败 → 补父目录创建
- **`effective_mode` 缺 `base_url` 判断**：配了 key 没配 base_url → daily 全线崩溃（违反"缺配置应降级"）
- **`AIPULSE_*` 环境变量覆盖全线失效**：yaml 字面量作为 init kwargs，
  在 pydantic-settings 下优先级压过环境变量 → 环境开关统一改用 `${ENV}` 占位符
- **`llm.timeout_s` 是死配置**：配置写 120s，实际吃 HttpClient 的 20s → 按 fast/strong 分档透传（strong 180s）
- **主编点评每日降级、永远为空**：`daily_brief.j2` 误用 strong 模型（reasoner 不支持结构化输出）
  → 改回 fast 档；同时**补第三级降级阶梯 `plain`**，降级状态改为按 `(model, format)` 记忆
- **分析窗口只覆盖约 7 小时**：collect 用滚动 24h、analyze 用"本地今天"，两处独立计算
  → 统一为共用 window 对象 + 滚动 24h，cron 改到北京 08:00（完整覆盖美西工作日）
- **预言证据 id 存在幻觉**：只校验数量（≥2）不校验存在性 → 增加 prompt 注入候选池 + 存在性校验两层防护
- **Actions 报告 commit 丢失**：`git pull --rebase` 在同日重跑时必然冲突
  → 改用 `git fetch` + `git reset --soft FETCH_HEAD`
- **记分板生成时间用 UTC** → 改本地时区
- **arXiv 429 限流** → 单源隔离正常生效，退出码仍为 0（**非 bug，是设计生效的证明**）

### Added

- 提速保护：`signals.min_velocity_window_hours: 6.0`，间隔不足标 `insufficient`（防止调试连跑污染数据）
- HTMX 收进本地 `static/`（不再依赖 CDN）
- `predictions.md` 输出证据 id 列 + 「证据条目对照」，查不到标 ⚠️（**让幻觉核验常态化**）
- Actions 三条持久化对策：报告 commit + cache 恢复 db + signals.json

### Changed

- `meta.analysis.entities` → `new_entity_mention_rows`（口径澄清：本次新增，非当日总数）
- 配置划线原则：环境开关用占位符，算法阈值留字面量（要 git 版本化）

---

## [m4] — Actions 自动化 + Web 看板 + 开源发布

**系统从这一天起每天自动跑。**

### Added

- `.github/workflows/daily.yml`：cron 定时 + `workflow_dispatch`；`AIPULSE_ENV=actions` 打开 `actions_only` 源
- Actions 持久化三条对策（报告 commit / cache 存 db / signals.json）
- Web 看板（`aipulse serve`，FastAPI + Jinja2 + HTMX）：首页 / 归档 / 记分板 / 主题 / 检索
  - 校准曲线用**内联 SVG**，零前端构建链
  - SQLite 以 `mode=ro` 打开（只读红线变成可执行断言）
  - 0 样本空态优雅降级
- 每日产物扩展：`scoreboard.md`、`verdicts.md`、`signals.json`
- `scripts/cron_daily.sh`（WSL 本地 cron 备份）
- README / CONTRIBUTING / issue 模板
- `notify` 抽象（Notifier Protocol + FileNotifier，仅 file）

### 统计

- 306 → 319 passed，TOTAL 89%
- Actions 实测：7 源全通 / 0 失败 / 165-185 条

---

## [m3b] — 预言系统 · 验证与统计 ★ 闭环

**★ 从这一版起，预言系统完整闭环，且 off 档零 API 花费可跑通全流程。**

### Added

- `reasoning/verifier.py`：双路径验证（量化判据查表零 LLM / 语义判据走证据门槛 → LLM 三值）
- 6 个量化判据模板（含 `custom` 受限 AST 求值）
- `analysis/stats.py`：命中率 / 加权分 / Brier Score / 5 桶校准表 / 5 维分组
- `render/scoreboard.py`：记分板 Markdown（含 0 样本空态）
- 人工兜底 `predict review`（`verified_by=human`，同样计入统计）
- `daily` 接入 `auto_verify`

### 统计口径（v1.9 裁定）

- 证据窗口 `[生成日, due_date+3天]`（左界从生成日起，避免早期兑现的 hit 被误判 miss）
- Brier 的 partial 按 `outcome=0.5`
- 校准分桶补 `[0.05, 0.5)` 低置信桶
- `unverifiable` 归 status 不归 verdict，**LLM 不得输出**（防"逃避 miss 的软出口"）

### 统计

- 229 → 272 passed，`analysis/stats` 覆盖率 100%

---

## [m3a] — 预言系统 · 生成

### Added

- `schema/prediction.py`（含 `origin` / `criteria*` 字段）+ 模糊措辞黑名单 + 硬校验
- `prompts/predict/generate.j2` + `configs/criteria.yaml`（6 个判据模板）
- `reasoning/predictor.py`：生成 → 硬校验 → 一次重写 → 仍不合法丢弃
- 手写预言 `predict add` **双模交互**（全参数非交互 / 缺参自动进向导，含判据模板选择与预览确认）
- 8 种模糊句拦截 + 1 个负向防误伤用例

### Changed

- **★ 移除 `openai` SDK**，改用项目自带 httpx 直连
  （原因：自带 httpx 2.x 与项目冲突，且导致 respx 无法 mock，覆盖率曾为 0%）
  → 改造后 `openai_compat` 覆盖率 **94%**
- json_schema 运行时自动降级（`auto|true|false`）

### 统计

- 180 → 229 passed

---

## [m2] — 打分 / 聚类 + 每日简报

### Added

- `analysis/`（score / cluster / entities / signals）
- `llm/`（NullLLM + FakeLLM + openai_compat + structured + cache + budget）
- `reasoning/brief.py`、`render/`（markdown / json_out）、`pipeline/daily.py`
- **★ 三档运行模式 `off` / `hybrid` / `full`**：无 API 也能跑完整流程
- off 档单测用 respx 断言 `route.call_count == 0`
- 改 `scoring.yaml` 权重无需改代码即生效
- 非法 JSON → 修复重试 → 再失败降级，全程不中断
- RSS 内部并发拉取（串行 298s → 并发，约 3.3x）

### 统计

- 142 → 180 passed

---

## [m1] — 6 个采集器 + inbox + 三级去重

### Added

- `collectors/`（GitHub Trending 双通道 / arXiv / HF / HN / Reddit RSS / RSS）+ `registry`
- `normalize/`（clean / dedup 三级去重）
- 跨源合并：arXiv 与 HF 同一篇论文合并为一条
- `docs/新增数据源指南.md`

### Changed

- arXiv 必须 `lookback_days: 7`（索引滞后 3-4 天，严格 24h 会采空）
- 三层内部隔离（feed / subreddit / 关键词失败不拖垮整个源）

### 统计

- 64 → 142 passed，collectors 覆盖率 87.7%
- 真实采集 107 条

---

## [m0] — 项目骨架 + 数据源探测

### Added

- 七层架构骨架、9 张表 + alembic 迁移
- `aipulse doctor` 体检表
- 6 个 API 源 + 2 个 RSS feed 的真实响应快照（fixtures）
- `docs/数据源手册.md`（字段全部摘自真实响应）
- 仓库公开（public）、MIT、CI

### 统计

- 64 passed

---

## 附：设计文档版本

`docs/AI_Pulse_设计方案_vN.md` 与 `docs/AI_Pulse_Agent开发执行手册_vN.md` 是**设计 SSOT**，
编号独立于代码 tag（当前 v1.14）。它们由项目负责人出全量版本并覆盖，Agent 只读不改。
