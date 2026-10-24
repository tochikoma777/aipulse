# 变更日志

本项目采用 [Keep a Changelog](https://keepachangelog.com/) 风格，按里程碑组织。
代码 tag：`m0`–`m4` 为里程碑，`m6a` 为 M6a 收尾，`star-tracking` 为 P0 功能 tag，`m6b` 为 M6b（条目增强）里程碑 tag，`m6c` 为 M6c（知识库）里程碑 tag；M6a 之后的追加工作使用功能名 tag，不占用里程碑编号。

**版本与 tag 的对应**：`m0`–`m4`、`m6a`、`star-tracking`、`m6b`、`m6c` 已发布；M5 的**趋势长文（S1–S3）与多角色辩论（S4）均已完成但未打 tag**（按项目纪律，tag 由项目负责人在 SSOT 版本号之前处理）。
**设计文档版本**（见 `docs/AI_Pulse_设计方案.md` 头部的 `v1.x`）与代码版本**独立编号**，不要混淆。

---

## [t9-auto-trigger] — trend/debate 自动触发（日历月，2026-10-24）

> 项目负责人拍板：trend 与 debate 都支持 auto+manual，默认 auto；**间隔 = 日历月**，
> 且「间隔」既是触发间隔也是分析范围——月度触发时分析整个自然月，
> 所以 `window_days` 不需要独立配置。命名用 `trigger_mode`（避开 LLM 三档）。

### Added

- **`pipeline.trend` / `pipeline.debate`**（`trigger_mode` + `interval`）：
  三态 `auto | manual | disabled`；`interval` 支持 `1m`（日历月）与 `Nd`。
  **`trigger_mode` 管准入门（要不要自动跑），`budget.degrade_order` 管退出序（钱不够先砍谁）。**
- **`core/schedule.py`**：日历月推导（`previous_month_bounds` / `window_for`）。
- **`reasoning/trend.py::slice_by_range`**：按日期范围切片——`last-N-days` 表达不了
  "分析整个 10 月"。
- **`aipulse watchlist`**（P0-3）：每日轻量核对，**只核对不新建、零 LLM 零网络**；
  写回合并后的 `data/reports/trend/watchlist.json`，各期目录保持只读。
  已接入 `daily.yml`（提交报告前一步）。
- **`.github/workflows/monthly.yml`**：每月 1 日跑 `trend → selfcheck → debate`（固定顺序），
  退出码分级：0 正常 / 1 质量失败 → `::warning::` 不标红 / ≥2 用法数据错误 → `::error::` 标红。

### Changed

- **`trend` 省略 `--range`** → 按 `pipeline.trend.interval` 取**上一个完整自然月**；
  显式 `--range` 优先；`disabled` 不给 `--range` 直接劝退；范围内一篇日报都没有 → exit 2。
- **`debate` 自动选题加两道闸门**：
  1. **时效守卫**（P0-2）：trend 产物的窗口结束日必须落在本期范围内，否则跳过并打印 top2 候选；
  2. **争议度门槛**（P1-5，默认 6 分）：最高分低于门槛 → 跳过，不硬产出没人看的辩论。
  跳过 = exit 0（只有真错误才非 0）。
- **debate 取材窗口跟随所辩论的那期 trend 产物**，不再默认"最近 7 天"。
- **`weekly_debate_enabled` 标 deprecated**：只在用户没显式配过 `debate.trigger_mode` 时
  才回退（`true→auto` / `false→manual`），并打一次 deprecation 日志。
  SSOT 同步后删除——在那之前直接删会留下"文档说有、代码没有"的坑。
- **同构段短尾巴可见**（P1-4 替代方案，项目负责人接受）：证据里明说
  「窗口 M 天中本段仅 N 天，其余 K 天因源集合变更或首段过短未参与份额对比」。
  **不改取段逻辑**——取最长段会破坏跨期可比，而 L4 整个设计依赖可比。

### Fixed

- **`_state_files` 真 bug**：`state_dir` 传 trend 根目录时 `parent` 是 `data/reports`，
  glob 不到各期文件 → 合并结果为空。改为同时看 `state_dir/*/` 与 `state_dir.parent/*/`。

### 实测

| 项 | 值 |
|---|---|
| trend 30d（10 天数据） | 8/8 调用、0 截断、13330+41519、**¥0.2194**、exit **0** |
| debate（显式 topic，与自动选题同题） | 9/9 调用、0 截断、22912+17061、**¥0.1599**、分歧 4、可用证伪 9/9 |
| 月度合计预估 | **¥0.38–0.51**（低于预估的 ¥0.5–0.8） |
| 自动选题时效守卫 | 今天 10-24 → 本期 9 月 → 最新产物 10-24 **被拦下**，exit 0 + top2 候选（8 分 / 5 分） |
| 争议度门槛 | 最高 8 分 ≥ 6，**会放行**（真实数据上不会月月跳过） |
| watchlist | 8 条历史（5 dropped / 1 still_on / 2 pending），L3 ✅ |

---

## [post-m5-cleanup] — 遗留清理 10 项（2026-10-24）

### Added

- **`aipulse debate` 自动选题**（C2）：省略 `--topic` 且 `pipeline.weekly_debate_enabled=true` 时，
  从最新 trend 产物挑争议度最高的板块，打印 `已自动选题：<topic>（来源：trend/<日期>）` 与逐条依据。
  争议度 = 4 个可观测信号（份额 |Δ|≥3pp +3 / 上期周报下过判断 +2 / 本期有 dropped +2 / 有未到期条目 +1）。
- **`aipulse doctor` 数据源健康**（C1）：读最近 7 天 `source_runs.json`，连续 ≥2 天整源 0 条 ⚠️、≥3 天 ❌；
  排除手动通道 `inbox` 与 `--no-collect` 日报。
- **30 天窗口**（C5）：`--range 30d` 可跑通；数据不足时明确报「请求 30 天，实际 N 天，还需再攒 M 天」，
  并写入 `weekly.json` 的 `caveats`。

### Changed

- **`DEFAULT_DIRECTION_EPS` 随窗口缩放**（C5）：`eps(N) = 0.5 * sqrt(5/N)`
  （5 天为原始锚点；7 天 0.423、30 天 0.204）。固定阈值会让长窗口对慢漂移过度迟钝。
- **L2「跨条目 = 0」降为 warn**（C3）：不再 pass；正文须显式回答「本期有无替代/背离」，
  缺失则在 findings 里点出「沉默略过」。
- **arxiv 错误可见性**（C1）：错误信息补异常类型名（超时类 `str()` 为空）；
  429 附「arXiv 要求 3 秒 1 次」提示；`rate_limit` 由 `3/s` 改为官方的 `1/3s`。
- **watchlist expectation 按 id 取分句**（C4）：一句两个 id 时不再重复存整句。
- **CI actions 升级**（C8）：`actions/checkout@v7`、`astral-sh/setup-uv@v10.3.2`（消除 Node.js 20 弃用提示）。

### Fixed

- **`aipulse selfcheck` 回退到最近一期周报**：日报每天有、周报按周产，最新一天通常没有 trend 产物，
  原先直接退出 2；现在回退并提示。
- **doctor 的 CLI 用例随仓库数据时红时绿**：改为 `tmp_path` 隔离。

### 核实（未改动）

- **死代码 `_item_comments()` / `ItemComments`**（C7）：全仓零引用，且早已不存在（只剩单数 `ItemComment`，仍在用）。
- **alembic 迁移漂移**（C9）：全新库 `alembic upgrade head` 后 `alembic check` → `No new upgrade operations detected.`，
  无模型漂移；本地 `data/aipulse.db` 停在 `d5a2c9b81e34`（落后一版）是历史状态，按约束不动。

### 实测

- CLI 覆盖率：`commands/trend.py` 40% → **97%**、`commands/debate.py` 86% → **99%**，`aipulse.cli` 合计 77% → **81%**
- 全量 **586 passed**，覆盖率 91%，主库 sha256 未变

---

## [post-m5] — 收口：数据健康 banner + 部署形态文档（2026-10-24）

### Added

- **数据健康 banner**（`render/weekly.py::health_banner`）：数据不健康时，在 `weekly.md`
  标题下方加一行，如
  `⚠️ 本周 arxiv 连续 4 天整源 0 条、hf_papers 连续 2 天整源 0 条、可判结构方向仅 2 条（<5），结论置信度有限`。
  触发条件：窗口内存在 failed/degraded 且 `item_count=0` 的来源，**或**可判结构方向 <5 条。
  正常时**不出现**（不做永久免责）。口径是"窗口内最长连续段"，不是"截至末日的连续段"——
  arxiv 连挂 4 天后恢复，只看尾巴会让整段故障消失。手动投喂通道 `inbox` 不算故障。
- **README「三种部署形态」**：纯本地 / Actions 托管 / 只读·知识库，附三句纠偏
  （cron 只管定时不管可用、GitHub 不是运行依赖、无外网仍可读已有报告）。

### Fixed

- **`scripts/cron_daily.sh` 注释订正**：原文写"本地库是权威副本"是**反的**。
  权威是 `data/reports/`（已 commit 的日报 JSON）；SQLite 只是当日中间库、git 不跟踪，
  Actions 只能靠 cache 续命。实测本地库停在 10-17，日报已到 10-23。

---

## [m5-readable] — 产物可读化（S5，未打 tag）

> 项目总原则：**专业的结构化数据要保留，但给人看的要符合人类阅读习惯**。
> 不是"为易读而丢数据"，而是**两层都保留、分层呈现**：
> 机器层看过程，人类层看结论。红线：不得为排版删掉 L1-L4 依赖的数据。

### Added

- **双层分离**：`weekly.md`（人类层）与 `weekly.json`（机器层）并存。
  机器层保留 7 节正文 + 裸 ID + violations + 免责口径，**L1-L4 改读它**（`sections_from_machine`），
  四层判定逻辑一行未改。
- **weekly.md 人类版**（`render/weekly.py`）：📌 本周三句话 → 🧭 本周判断 → 📊 板块份额表
  （Unicode 条形图 `███░░`）→ 🔥 跌出 Top30 → 🎯 下期观察 → 折叠免责 → 文末数据溯源。
  **正文零裸 ID**，条目一律 `[标题](url)`。
- **debate 人类版**（`render/debate.py`）：结论卡片（**置信度置顶**）+ 四方「立场一句 + 3 条核心论据 + 折叠全文」
  + **交锋矩阵**（质疑方→被质疑方｜核心一击｜结果）+ **证伪条件表格** + 折叠的让步与不可用项。
- **第 8 次调用**（`prompts/trend/headlines.j2`）：把 7 节正文压成三句话（≤40 字/句，禁免责措辞、禁裸 ID）
  与各节判断性结论。表格数字由 `cross_period` 确定性渲染，不经模型。

### Changed

- **产物按窗口结束日分目录**，不再用固定名覆盖：
  `data/reports/trend/<窗口末日>/{weekly.md,weekly.json,selfcheck.*,watchlist,calibration}`、
  `data/reports/debate/<窗口末日>/<slug>.{md,json}`。跨期历史是 L3/L4 的输入，覆盖即丢。
- **状态文件合并读取**：`_load_state()` 合并各期目录的 `watchlist.json` / `calibration.json`，
  否则分目录后跨期回检会失去历史。
- **`cron_knowledge.sh` 脏树检查限定范围**：`git diff --quiet -- . ':!data/reports/trend' ':!data/reports/debate'`
  ——生成物重跑即脏，不该永久阻断知识库导出。
- **`aipulse selfcheck` 默认读 `weekly.json`**；`--file` 仍可指定旧格式 Markdown。

### L4 判据修正（2026-10-23 裁决）

- **检验对象换成「结构性判断的方向是否延续」**：上期记录的板块/来源方向
  （`heat_migration.direction` + `source_share.count_delta_pp` 符号）在本期是否同向 → 延续率。
  条目存活率降为**辅助指标，不单独触发 fail**——结构判断是关于板块的，
  板块份额上升不代表代表条目必须在榜；三条全跌出也证伪不了「社区舆论在收缩」。
- **前置门**：回检间隔 <7 天、或可判样本 <5 条 → `insufficient`（不是 fail）。
  1 天内跌出是常态基线（日换血 70%+、66% 条目只出现 1 天）。
- **反馈闭环**：`build_admission()` 把回检结论转成下期准入，落 `<issue>/admission.json`；
  `trend` 启动时读最近一期，`fail → strict`（只允许 1 条结构判断）、
  存活率 <34% → `tight`（最多 2 条）、`insufficient → normal`（没证据不收紧）。
- 本轮 0/3 保留为 calibration 首个观测点，不丢弃也不当结论。

### 实测

- trend：窗口 2026-10-17→10-23，8/8 调用、0 截断、token 11578+33236、**¥0.1793**
- debate：窗口同上，9/9 调用、0 截断、token 23474+18601、**¥0.1661**、可用证伪 9/9、分歧 4 条
- `weekly.md` 正文裸 ID **0**（全文 9 个，全在文末溯源区）
- 主库 sha256 保持 `dbc4b2ae…d847`

---

## [m5-debate] — 多角色辩论（S4，未打 tag）

> 目标：让四个立场不同的角色就同一议题互相质证，把「单一视角的自信」压成
> 「有分歧、有翻转条件」的结论。本段全部自 evaluator 实测：
> `data/reports/debate/debate-Agent-类项目密集进榜-真实采用还是单日脉冲.{md,json}`。

### Added

- **多角色辩论**（`reasoning/debate.py` + `schema/debate.py` + `prompts/debate/{round1,round2,moderator}.j2`）：
  乐观 / 怀疑 / 工程 / 投资四方 `asyncio.gather` **并行**陈述 → 交叉质证（能看到其他三方观点）
  → 主持人收敛为五项输出：共识 / **关键分歧** / 可执行结论 / 整体置信度 / 什么证据会让我改变判断。
- **`aipulse debate --topic "…"`**：`--range` / `--json` / `--out` / `--max-tokens` / `--reports-dir`。
  落盘 `data/reports/debate/debate-<slug>.{md,json}`，**不入库**（`build_client(engine=None)`，同 trend）。
- **★ 证伪条件可判定性校验**（`schema/debate.py::falsification_violations`）：
  必须是**单一二元可观测状态**，禁止数值阈值、禁止两个独立问句合取。
  S3 的 watchlist 出过悬空判定（热度 82.82 既不 ≥82.89 也不 <82.06，两个分支都不触发），
  本校验就是为堵住这类"点值区间造灰色地带"。
- **证据包按板块轮转取材**：≤15 条、每条 ≤60 字，只给 `id + 标题 + 热度 + 板块`，
  **绝不回显摘要原文**（v1.17 事故：predict 因回显输入使输出膨胀 10 倍撞 `max_tokens` → 生成 0 条）。

### Changed

- **失败判据**：`key_disagreements` 为空判失败（四方收敛成 bland 共识是最大失败模式）；
  任一方未引用具体 `item_id` 判该轮无效；`finish_reason == length` 明确报错。
  **证伪条件不合格只标记"不可用"、不判整场失败**——只有可用数为 0 才是真的没有可判定结论
  （与 S2.6 拒绝「斜率唯一」同一理由：不用过度保守换掉有效结论）。
- **并发前先做一次预热探测**：结构化格式阶梯是模块级进程内记忆，四方同时起跑会各自
  重走三级降级（strong 档实测三级全不支持 → 首跑最多 12 次请求）。预热后实测 11 次请求。

### 实测

- 9/9 调用成功、0 截断、token 26671+18478、**成本 ¥0.1806**（含预热探测）
- 可用证伪 **9/9**、关键分歧 4 条非空、置信度 0.34
- 证据包板块分布：论文与研究 4 / 开源项目 4 / 社区舆论 4 / 产业与新闻 3
- 主库 sha256 保持 `dbc4b2ae…d847`

---

## [m5-trend] — 周期趋势长文 + 自验证（未打 tag）

> 目标：把「跨期结构」先算出来，再让模型解释。M6b 已实证「让模型自主挑选」会让
> why 覆盖率崩到 4%，所以趋势必须由代码算，模型只负责解释与判断。
> 本段全部自 evaluator 实测：`data/reports/trend/weekly.md` + `selfcheck.md`。

### Added

- **跨期轨迹层**（`analysis/cross_period.py`）：按 `item_id` 组织窗口内「在榜 / 热度」轨迹，
  再据此算 9 个结构——热度迁移、共动聚类、背离、替代对、涌现断档、持续性、来源份额、
  预言复盘、未发生的预期。每个结构统一输出 `entry_count` / `status` / `required_days`
  （数据不足时明确「还差多少天」，而不是记 0 条）。
- **趋势长文**（`reasoning/trend.py` + `prompts/trend/weekly.j2`）：按 7 节分段生成，
  每节一次调用（单次写 2000-4000 字会撞 `max_tokens`）。每节独立校验字数、锚定 id、
  套话、违规，坏一节不影响其余六节。
- **`aipulse trend --range 7d`**：`--json` / `--out` / `--segments`（只重跑某节）。
  用量走内存记账，**不写主库**。
- **`aipulse selfcheck`**：L1 硬判据 / L2 信息增量 / L3 跨期回检 / L4 校准追踪，纯离线。
  状态落 `data/reports/trend/{watchlist,calibration,selfcheck}.json`，下期自动核对。
- **`data/reports/trend/`**：周报本体 + 自检报告 + 两份跨期状态，随仓库入库。

### Changed

- **`daily.json` 的 30 条是 brief 渲染集（Top30），不是全量语料**：相邻两日重叠仅 7–9 条，
  所以「今天不在榜」一律写「跌出 Top30」，禁止写「消失」。这是本项目最容易产出的
  "像洞察的假话"，代码里已改死（`KIND_DROPPED`）。
- **① 的方向改为以斜率为准**（阈值 ±0.5pp/天），首末差只作幅度参照；
  两者不一致时证据里直接标 ⚠，并要求正文同时给出两个数字。
  理由：5 天窗口里首末两点仍被单日波动主导（社区舆论首末 +2.77pp 而斜率 −0.64）。
- **份额对比只在「源集合同构」区间内进行**：10-15/16 只有 3 个源、10-17 起 5 个源，
  跨这个变更日比较会把「源扩容」读成「板块迁移」——实测社区舆论 7 天 +22.80pp，
  同构区间仅 +2.77pp，方向甚至相反。段长 <3 天直接判数据不足（为 30 天窗口预留）。
- **采集失败日从跨天计算中剔除**：板块「夹在两次有数据之间」的 0 条日按坏日处理
  （不累计轨迹、不进斜率）；某源 `failed/degraded` 且 `item_count=0` 时，
  对应板块/来源标记 `trend_usable=False`，prompt 禁止对其作结构性判断。
- `max_tokens_strong` 8000 → 10000（按实际 token 计费，上限不是目标）。

### Fixed

- **`finish_reason=length` 明确报错**（此前全仓 0 处检查）：截断不再表现为
  "输出变短 / JSON 解析失败"，而是抛 `LLMTruncationError`，且 token 仍计入成本、不写缓存。
- **`budget.degrade_order` 真正生效**：此前只被存进字段、没有任何代码遍历它；
  现在按 `debate → trend → brief_topn → all` 逐级降级（每超一个日额度升一级）。
- **`spent_today()` 双计**：`record()` 已写库的花费又被叠加了一次内存记账，实测 0.5 元记成 1.0 元。
- **本地 `.env` 从未被读取**：`load_settings` 先 `Settings(**yaml)`（init 参数优先于 `env_file`），
  且全仓没调用过 `load_dotenv()`——CI 注入环境变量能跑，本地按 README 写 `.env` 永远读不到。

### 实测（2026-10-16 → 10-22，比较区间 10-17 → 10-22）

- 周报：7 节 / 2427 字 / 24 个锚定 id / 套话 0 / 违规 0；9 次调用、¥0.2475
- 自检：L1 pass、L2 新增结论 6 条（结构类，跨条目 0）、L3 无到期预言 + watchlist 历史核对 2 条
  （仍在榜 1 / 跌出 1）、L4 上期结构声称存活 2/3（67%，仅隔 1 天，只作机制验证）
- 数据侧：`hf_papers` 故障仅 10-17、10-18 两天（10-19 起恢复到 20/12/16 条），
  10-18 论文板块 0 条是「采集失败 + 24h 滚动窗口」叠加，不是话题退场

---

## [m6c] — 知识库：本地笔记 + 导出为可消费的 Markdown

> 目标：把日报条目沉淀成能直接喂给任意 AI 工具的本地知识库；
> 主库 `data/aipulse.db` 全程只读，笔记存独立 `data/user_data.db`。

### Added

- **独立用户库**：`knowledge_items` / `schema_version`，`create_all` 建表、不走 alembic；
  路径固定 `data/user_data.db`（`data/` 顶层，`.gitignore` 的 `data/*.db` 可覆盖）。
- **主库只读守卫**：`store/db.py::readonly_engine_for()`（SQLite `mode=ro`）；
  测试断言知识库操作前后主库 **size / mtime / sha256 三不变**。
- **daily index**：扫描 `data/reports/**/daily.json`，构建 `item_id` / `url` / `title` 映射；
  兼容 10-15/16 空 `comments`、10-17 `why_it_matters`、10-18 `why` 与字段缺失。
- **知识库 CLI**：`knowledge mark` / `note` / `items` / `list` / `export`；
  支持位置 `item_id`、`--url`、`--query` 三种定位（三选一）。
- **导出引擎**：`Exporter` Protocol + `MarkdownExporter`，输出
  `index.md` / `my-notes.md` / `topics/<slug>-<YYYY-MM>.md`；按 500 条或 200KB 分片。
- **`scripts/cron_knowledge.sh`**：方案 E，独立于本地 `daily`，只做
  `git pull --ff-only` + `knowledge export`，避免 `data/reports/` 未跟踪文件阻断。

### Changed

- `knowledge export` 默认包含未读条目，`skipped` 默认排除；`--include-skipped` 可含。
- `item_id` 现在查 daily index 校验；索引外条目需显式 `--allow-unknown`
  （避免打错字符存下永远导不出的孤儿笔记）。
- 用户库 `note` 更新保留 `created_at`、更新 `updated_at`；重复导出按条目日期与固定排序保持幂等。
- `scripts/cron_knowledge.sh` 工作区检查只看已跟踪/已暂存改动
  （`git diff --quiet` / `git diff --cached --quiet`），避免 `data/inbox/` 等未跟踪文件长期阻断。

### Fixed

- **`item_id` 在 `brief.md` 与 Web 页面中均不显示**：新增 URL / 标题查询入口；
  `--query` 多条候选只列出、不自动选择，命中 0 条明确报错。
- **历史 `daily.json` 结构不统一**：索引兼容 `why` / `why_it_matters` / 空 comments / 字段缺失。
- **导出失败静默**：cron 检查 export 退出码并记录 `export OK total=N` / `export FAILED exit=N`。

### 实测

| 指标 | 数值 |
|---|---|
| 真实 5 份 daily.json | 113 条，带 why 51（45.1%） |
| 导出文件 | `index.md` / `my-notes.md` / 4 个 topic 文件；最大 25 KB |
| 引擎耗时 | 1.96 ms（索引另计约 1.43 ms） |
| 幂等 | 重复导出所有文件 sha256 一致 |
| 主库 | `dbc4b2ae…c1d847` 全程未变 |
| 测试 / 覆盖率 | 407 passed / 90% |
| LLM 成本 | 0 元/日（导出不调 LLM） |

> `m6c` tag 指向 `c9b2fa1`；SSOT 文档 v1.22 随收口提交更新。

---

## [m6b] — 日报条目 why/stance 全覆盖 + 中文要点

> 目标：日报渲染集里的**每一条**都有「为什么重要 / 立场」，英文条目的要点强制中文。
> 此前 brief v3 只让模型自选几条点评，覆盖率不稳定——这正是"详略不一"的另一半。

### Added

- **`item_enhance` 表 + 迁移 `e6b2f7c1a9d4`**：条目级增强结果持久化
  （`one_liner` / `why` / `stance` / `content_hash` / 双 prompt 版本 / 热度与信号基线）
- **`prompts/brief/item_enhance.j2`**：why/stance 独立批量调用，含正反例表与套话禁用清单
- **`ItemComment` 新契约**：`item_id` / `one_liner` / `why` / `stance`；
  新增 `OneLinersOut` / `EnhancesOut` 等轻量结构化输出模型
- **`brief.enhance_*` 配置**：`enhance_top_n=30`、`enhance_batch_size=10`、
  `enhance_budget_cny=0.15`、`enhance_ttl_days=30`、`enhance_refresh_hot_delta=10.0`、
  `enhance_refresh_on_new_signals=false`
- **`meta.json` 新增计数**：`enhance_total` / `enhanced` / `enhance_skipped_count` /
  `enhance_cache_hit` / `enhance_cost_cny`

### Changed

- `prompts/brief/item_comment.j2` 升 v2：只产中文要点，不再产出 why/stance，顶层键 `one_liners`
- 增强挂 `mode` 档（零新增开关）：`off` 只读表 / `hybrid` 只补缺失（生产默认）/ `full` 忽略缓存全刷
- `ItemComment` 移除 `who_cares` / `what_to_watch` / `novelty` / `impact`（从未被渲染）
- Web 看板「为什么重要」列兼容旧归档（`why` → `why_it_matters` 回退）

### Fixed

- Actions `runs-on` 固定 `ubuntu-24.04`（三处 workflow），避开 2026-10-19 的 Ubuntu 26 迁移

### 实测（Actions run 39112189002 / 39112974821）

| 指标 | 数值 |
|---|---|
| enhance_total / enhanced | 23 / 23（skipped 0，全覆盖成立） |
| 冷启动 / 全刷成本 | **0.011862 元/天**（4.33 元/年） |
| 稳态成本（第二次跑） | **0.002768 元/天**（1.01 元/年） |
| 缓存命中 | 20/23（3 条新条目按设计补算） |
| 套话命中 | 0（值得关注 / 未来可期 / 有望 / 具有重要意义…） |

---

## [star-tracking] — M6a 收尾 + P0 star 追踪

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

### [M6a] 格式规范化 + 快照型源修复

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

`docs/AI_Pulse_设计方案.md` 与 `docs/AI_Pulse_Agent开发执行手册.md` 是**设计 SSOT**（当前 **v1.20**），
文件名固定，版本号写在文档头；编号独立于代码 tag。它们由项目负责人出全量版本并覆盖，Agent 只读不改。
