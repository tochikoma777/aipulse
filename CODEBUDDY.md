# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## ★ 当前阶段：已结项（M0–M6c + M5 + T9 全部完成）

**一句话**：M0–M4、M6a/b/c、M5（趋势长文 S1–S3 / 多角色辩论 S4 / 产物可读化 S5，
tag `m5`）、T9（trend/debate 自动触发 + `aipulse watchlist`，tag `t9`）全部完成并真跑验证。
系统每天自动跑（Actions `daily`），每月 1 日自动跑趋势与辩论（Actions `monthly`，
实跑验证 run 40097659576）。

| M5 落点 | 现状 |
|---|---|
| `analysis/cross_period.py` | ✅ 9 个跨期结构 + 轨迹层 + 坏日/源集合变更归因 |
| `reasoning/trend.py` · `schema/trend.py` · `prompts/trend/weekly.j2` | ✅ 7 节分段生成（每节一次调用） |
| `reasoning/selfcheck.py` · `cli/commands/selfcheck.py` | ✅ L1–L4 自验证（离线，0 成本；**读 `weekly.json` 机器层**，状态合并各期目录）。**L4 检验的是上期结构方向是否延续**（不是条目存活），间隔 <7 天或样本 <5 判 `insufficient`；结论写 `admission.json` 供下期 `trend` 收紧门槛 |
| `data/reports/trend/<窗口末日>/` | ✅ `weekly.md`（人类层）/ `weekly.json`（机器层）/ `selfcheck.{md,json}` / `watchlist.json` / `calibration.json` |
| `render/weekly.py` · `render/debate.py` · `prompts/trend/headlines.j2` | ✅ S5 人类层渲染（三句话 / 表格 / 交锋矩阵 / 折叠免责 / 文末溯源） |
| `schema/debate.py` · `reasoning/debate.py` · `prompts/debate/{round1,round2,moderator}.j2` | ✅ 四方并行 → 交叉质证 → 主持人收敛（实跑 9/9 调用，¥0.18） |
| `reasoning/auto_topic.py` · `core/schedule.py` | ✅ 自动选题：4 信号争议度打分 + **时效守卫**（trend 产物必须属于本期）+ **争议度门槛**（默认 6 分，低于则跳过）；日历月推导 |
| `cli/commands/watchlist.py` | ✅ 每日轻量核对 watchlist（只核对不新建、零 LLM），daily.yml 每步都跑 |
| `data/reports/debate/` | ✅ `debate-<slug>.{md,json}`（不入库，只落盘） |
| `pipeline/weekly.py` | ⬜ 不存在（周报靠 `aipulse trend` 手动/cron 触发） |
| `web/app.py` 的「趋势」「辩论」入口 | 「趋势」可读 `data/reports/trend/weekly.md`；「辩论」仍置灰 |
| debate 的 auto 模式（从 trend 挑本周最大争议话题） | ⬜ TODO：需先把「分歧度」定义成可计算的量 |

**debate 验收要点（手册 §6 DoD，别做偏）**：四个 persona **必须 `asyncio.gather` 并行**（串行视为不合格）；证据包每条 ≤60 字、合计 ≤15 条、**绝不回显摘要原文**；收敛块必须含「什么证据会让我改变判断」。

**★ L4 判据（别改回去）**：主判据 = 上期记录的**结构方向**（`heat_migration.direction` / `source_share.count_delta_pp` 符号）在本期是否同向；前置门 = 间隔 <7 天或可判样本 <5 → `insufficient`（**不是 fail**）；条目存活率只是辅助指标，**不单独触发 fail**（板块结构≠条目在榜）。反馈闭环：`admission.json` → `trend` 的 `admission_rule`。

**★ L2 判据（C3）**：跨条目关系 = 0 **不算 pass**（降 warn）——结构/实体增量再多也没回答「谁替代了谁」；正文必须显式回答「本期有无替代/背离」，缺失即判「沉默略过」。「跨条目=0 + 明说无可验证」仍是 warn，不是 pass。

**★ 触发配置（T9，两套开关别混）**：`pipeline.{trend,debate}.trigger_mode` 管**准入门**（auto/manual/disabled，不是 LLM 三档 off/hybrid/full）；`budget.degrade_order` 管**退出序**（钱不够先砍谁）。前者是计划，后者是预算。`interval` 既是触发间隔也是分析范围（`1m`=上一个完整自然月）。

**★ 方向阈值随窗口缩放（C5）**：`direction_eps(N) = 0.5 * sqrt(5/N)`（5 天为锚点）。**不要写死 0.5**——固定阈值会让 30 天窗口对慢漂移过度迟钝。

**★ 双层分离（S5，跨 trend/debate 通用）**：机器层看过程，人类层看结论。`weekly.json` 保留 7 节正文 + 裸 ID + violations + caveats，**L1-L4 读它**；`weekly.md` 只给结论（三句话 + 判断 + 表格），**正文零裸 ID**，免责进 `<details>`，ID 收进文末「数据溯源」。
★ 红线：不得为了排版好看而删掉 L1-L4 依赖的数据——数据是**移位**，不是删除。

**★ 证伪条件必须可判定（跨 trend/debate 通用）**：必须是**单一二元可观测状态**（如「10-23 是否仍在 Top30」），禁止数值阈值、禁止两个独立问句合取（4 种组合状态对 2 个分支必然覆盖不全）。校验器在 `schema/debate.py::falsification_violations`。不合格的条件**只标记不可用、不判整场失败**——只有可用数为 0 才是真的没有可判定结论（与 S2.6 拒绝「斜率唯一」同一理由：不用过度保守换掉有效结论）。

**M5 里已经踩死、不要重犯的四条**（详见 `docs/开发日志.md` 的 M5「坑」）：
1. `daily.json` 的 30 条是 **brief 渲染集（Top30）**，不是全量语料——「今天不在榜」只能写「跌出 Top30」。
2. **采集失败 / 板块口径变更 / 源集合扩容都会伪装成趋势**。归因链已在 `cross_period` 里做好（`attribution` / `masked_days` / `source_change_days`），新结构必须复用，不要绕开自己算。
3. **LLM 不负责"发现趋势"**，只负责解释代码算出来的结构。让模型自由挑选的路径已被 M6b（why 覆盖率 4%）和 M5（真新 66% 是单日闪现）各证伪一次。
4. **证据包不能只按热度取**。S4 首跑 15 条里 14 条是「论文与研究」，四方被锁进同一个"论文 vs 非论文"框架，分歧是假的。现在按板块轮转取材（每板块 Top 3-4）。

**阶段顺序是红线**（手册 §0.3 第 7 条）：不要跨阶段实现，也不要在 M5 里回头重写已完成阶段的产物。开工前先按下方「改哪里 → 先跑什么」确认基线是绿的。

## 开工前必读

> **off 档跑得再久也覆盖不了 hybrid/full 路径。** 涉及 LLM 的改动，本地桩测试全绿不等于真实可用——必须配 key 实跑一次才算验证过。
>
> 依据：M4 的 `data/` 目录缺失、以及首跑 hybrid 连炸 5 个 bug（缺 `base_url` 崩溃、`AIPULSE_MODE` 被 yaml 字面量压掉、`llm.timeout_s` 是死配置、证据 id 幻觉、窗口只覆盖 7 小时），**全部只有真实运行才暴露**，桩测试一条都没抓到。

## 项目身份

`aipulse`（AI 脉搏）：每日采集 AI 领域热点，产出可回测的推演与预言。Python 3.11 + `uv`，SQLite 单文件存储，MIT。

### 里程碑

| 阶段 | 内容 | 状态 / tag |
|---|---|---|
| M0 | 骨架 + 数据源探测 | ✅ `m0` |
| M1 | 6 采集器 + inbox + 三级去重 | ✅ `m1` |
| M2 | 打分 / 聚类 / 实体 + LLM 抽象 + 简报 | ✅ `m2` |
| M3a | ★ 预言生成 + 手写 + 不可证伪拦截 | ✅ `m3a` |
| M3b | ★ 到期验证 + 命中率 / Brier / 校准度 | ✅ `m3b` |
| M4 | Actions 自动化 + Web 看板 + README 发布 | ✅ `m4` |
| M6a | 快照型源修复 + 简报格式规范化 + predict 截断修复（2026-10-17，真跑验证） | ✅ `m6a` / `4a12fa3` |
| P0 | star 追踪：★ 总数 / 增量两列、增速榜、`source_runs.json` | ✅ `star-tracking` / `cdcab79` |
| M6b | 日报条目 why/stance 全覆盖 + 中文要点（2026-10-18，冷启动 0.011862 元/天） | ✅ `m6b` / `11fb09a` |
| M6c | 知识库：双库隔离 + 笔记 CLI + daily index + Markdown 导出 + `cron_knowledge.sh`（2026-10-20） | ✅ `m6c` / `c9b2fa1` |
| **M5** | **周期趋势长文 + 多角色辩论 + 产物可读化** | ✅ `m5`（S1–S5 全部真跑；产物在 `data/reports/trend/<末日>/` 与 `data/reports/debate/<末日>/`） |

`git tag` 全集就是上表这些，**没有 `m6` 不是漏打**（`m6a`/`m6b`/`m6c` 是插在 M6 之前的修复与增量阶段）。P0 的 Actions 实跑证据：`data/reports/2026/10/17/` 由 `aipulse-bot` 提交，`generated_at 2026-10-17T14:55Z`，含 `source_runs.json`。M5 的落点在文首表格，**S1–S5 已全部实现完毕**（trend / selfcheck / debate 都可直接跑）。

### 当前 HEAD 与 tag 的关系

HEAD 在 tag `m5`（`4244cae`）之后约 30 个提交，包含 post-m5 收口（数据健康 banner /
README 三类部署形态 / `cron_daily.sh` 口径订正 / CI 修复）与 T9（自动触发）。
T9 已打 tag `t9`（指向 `5b2fad2`）。

### 文档版本基线

SSOT 两份文档当前 v1.22（`docs/文档维护日志.md` 最新一条 v1.22 = tag `m6c` / `c9b2fa1`）。文件名固定为 `docs/AI_Pulse_设计方案.md` 与 `docs/AI_Pulse_Agent开发执行手册.md`，**版本由 git 管理，不再写进文件名**。`docs/文档维护日志.md` 的「维护记录」表按**倒序**维护（新的在上），**该表顶部第一行**的 tag 才是「文档对应哪次提交」的唯一锚点（注意不要读上半部分的格式示例，那里的 v1.20 只是样例）。新会话先读它确认基线。**SSOT 两份文档与 `docs/文档维护日志.md` 是 Agent 只读，不得修改**；文档维护必须「先提交代码 + 打 tag，再刷新文档」。

### 新会话开场顺序

① `git log --oneline -5` + `git tag`（代码到哪）；② 读 `docs/文档维护日志.md` 的「维护记录」表顶部（不是文件末尾、也不是上面的格式示例）（文档基线）；③ `docs/开发日志.md` 末尾一章 + `CHANGELOG.md` 顶部（上一阶段的结论与坑）；④ 最新一天的 `data/reports/YYYY/MM/DD/meta.json` 的 `window` / `mode` / `llm` + `source_runs.json`——最快看出「系统是否真跑过、哪些源 `skipped_offline`、档位有没有生效」。

### CLI 现状

已实现的 CLI：`init` / `doctor` / `collect` / `analyze` / `brief` / `daily` / `predict`（`add` / `list` / `verify` / `review`）/ `stats`（`stats --predictions`）/ **`serve`（M4 只读看板）** / **`inbox`（`add` / `add-file` / `list`，v1.1 手动投喂通道）** / **`knowledge`（`mark` / `note` / `items` / `list` / `export`，M6c）** / **`trend`（`--range 7d` / `--json` / `--out` / `--segments`，M5）** / **`selfcheck`（L1–L4，M5）** / **`debate`（`--topic` / `--json` / `--out`，M5 S4）**。

`src/aipulse/cli/commands/` 下其余子应用（`normalize`/`debate`/`trend`/`topics`/`search`/`sources`）仍是 `placeholder_app()` 生成的占位，调用时抛 `NotImplementedError`。它们出现在 `--help` 里是刻意的，不是漏实现。其中 `sources` 占位**不影响加源**：增删 RSS/Atom 源改 `configs/sources.yaml` 即可（见「采集器六条约定」末段）。

### M4 已落地的东西（改之前先看这里，别重复造）

`src/aipulse/web/` 是完整的只读看板（FastAPI + Jinja2 + HTMX，见模块表）；`cli/commands/serve.py` 是真实现；`.github/workflows/` 三个工作流——`ci.yml`（push/PR：ruff + format + mypy + pytest）、`probe.yml`（手动数据源探测）、**`daily.yml`（每天 00:00 UTC = 北京 08:00 跑 `aipulse daily` 并 commit `data/reports`；提交前先 `fetch` + `soft reset`，同日重跑不会因历史分叉冲突）**。`scripts/cron_daily.sh` 是 WSL 本地 cron 备份入口。

### Actions 没有持久化（改 daily.yml 前必读）

runner 每次都是全新机器，靠三条对策续命——① **报告文件 commit 回仓库**（`data/reports/` 文本即数据库，`permissions: contents: write`，提交前 `fetch` + `reset --soft`）；② **`actions/cache` 恢复 `data/aipulse.db`**（key 必须每次 run 唯一 `aipulse-db-${{ run_number }}` + `restore-keys: aipulse-db-` 前缀，按周/月复用 key 会让本周运行命中旧 cache 而不再回写）；③ **star 增速落 `signals.json`**，cache 丢了也能从历史报告回溯。

档位与密钥都在 workflow 里显式声明：`AIPULSE_MODE=hybrid` + `AIPULSE_ENV=actions`（**少了后者，`actions_only` 的 reddit / hf_papers 会被当成"本地"而跳过**）+ `AIPULSE_LLM__BASE_URL: ${{ vars.AIPULSE_LLM__BASE_URL || 'https://api.deepseek.com/v1' }}`（repo variable 不会自动注入 step env，缺它 base_url 被插值成空串 → 静默降级 off，表现为"配了 key 却什么都没生成"）。配 key：`gh secret set AIPULSE_LLM__API_KEY`；未配则自动降级 `off`，**记分板只会增长手写预言**。

### 知识库导出（M6c）

主库 `data/aipulse.db` 全程只读，笔记写 `data/user_data.db`；`aipulse knowledge export` 扫描 committed `data/reports/**/daily.json` + 本地笔记，输出 `data/knowledge/{index.md,my-notes.md,topics/*.md}`，幂等、不调 LLM。`scripts/cron_knowledge.sh` 是方案 E 的独立导出入口：**不跑本地 daily**，只 `pull --ff-only` + export；工作区检查只看已跟踪改动（`git diff --quiet` / `git diff --cached --quiet`），避免 `data/inbox/` 等未跟踪文件永久阻断。

### 看板代码的三条铁律

① `web/data.py` 用 `mode=ro` URI 打开 SQLite，写操作会直接抛错（红线 22 已变成可执行断言）；② 模板里取 dict 一律用**下标** `meta.analysis['items']`——Jinja 的 `foo.bar` 先取属性，`.items` 会命中 `dict.items` 方法本身（踩过）；③ 数据只读 SQLite 与 `data/reports/*.json`，不额外持久化任何东西。

### 对外承诺与不可动口径

改这些 = 改公共承诺，不是纯内部重构：README 的「★ 预言记分板」是项目唯一的护城河，数字由 `aipulse stats --predictions --markdown` 生成后**手工贴入、标注"请勿手改"**——`data/reports/.../scoreboard.md` 是每日自动生成物，README 里的是对外快照，两者都不要手改数字。手写预言（`origin=human`）与 LLM 预言（`origin=llm`）在记分板**完全同权**，因此可对比"人 vs 机器"校准度。统计口径不可动：`pending` / `unverifiable` 不入分母、`partial` 按 0.5 计、校准分桶必须保留低置信桶 `[0.05, 0.5)`；`unverifiable` **只由系统证据门槛产生**，LLM 不得输出。

---

## 常用命令

环境：必须在 WSL2 原生 ext4 文件系统内（**不要放 `/mnt/c/`**：I/O 极慢、SQLite 锁异常、git 行为诡异）。

```bash
uv sync                                   # 安装依赖（含 dev 组）；本地唯一的"构建"步骤（hatchling wheel，无需 uv build）
uv sync --frozen                          # 严格按 uv.lock 安装，不改锁文件（CI 用这个）
uv run aipulse --help                     # 命令树
uv run aipulse init                       # 建库（alembic upgrade head）+ 目录骨架 + .env
uv run aipulse doctor                     # 环境体检：Python/LLM key/代理/磁盘/DB/各源连通性
uv run aipulse collect --since 24h        # 采集（单源失败隔离，退出码恒为 0）
uv run aipulse collect --sources arxiv,hackernews --dry-run --json
uv run aipulse doctor --no-network --json # 离线体检

uv run aipulse analyze --date today --json            # M2：打分 + 聚类 + 实体统计（纯算法，零花费）
uv run aipulse brief  --date today --skip-llm         # M2：生成简报（零 API 花费的数据版）
uv run aipulse brief  --date today --top-n 10 --json  # 简报 JSON 到 stdout，日志走 stderr
uv run aipulse daily  --since 24h --skip-llm          # M2：collect → analyze → brief → render 一条龙
uv run aipulse daily  --no-collect --skip-llm         # 跳过采集，只做分析 + 简报（离线开发常用）

uv run aipulse predict --date today --json            # M3a：从当日 Top 条目自动生成可证伪预言（hybrid/full 档）
uv run aipulse predict --skip-llm                     # off 档：不产生 LLM 预言（手写才是 off 档核心）
uv run aipulse predict add --yes                      # 手写预言（参数齐全、跳过预览；缺参自动降级为交互式向导）
uv run aipulse predict add --criteria github_stars_reach --param repo=vllm-project/vllm --param threshold=90000
uv run aipulse predict list --status pending --json   # 按状态（pending|verified|unverifiable）/来源（human|llm）列出

uv run aipulse predict verify --due-date 2026-10-11 --json  # M3b：到期验证（量化判据零 LLM；语义走证据门槛→LLM）
uv run aipulse predict verify --skip-llm --db data/aipulse.db  # off 档：只做量化判据自动判定，零网络
uv run aipulse predict verify --limit 5                    # 最多验证 N 条（调试用）
uv run aipulse predict review pred_xxxx --verdict hit --note "依据：xxx 已于 10-09 发布"  # 人工兜底，verified_by=human
uv run aipulse stats --predictions --json             # M3b：命中率 / 加权分 / Brier / 校准表 / 分组
uv run aipulse stats --predictions --markdown         # 记分板 Markdown（可直接贴 README）
uv run aipulse stats --predictions --out data/reports/scoreboard.md  # 落盘

uv run aipulse serve --port 8000                      # M4：只读看板（今日/归档/记分板/主题/检索）
uv run aipulse serve --port 8000 --db data/aipulse.db --reports-dir data/reports

uv run aipulse inbox add <url> --note "..."           # 手动投喂一条（v1.1 微信/X 唯一合规入口；抓不到也保留，标题退化为 URL）
uv run aipulse inbox add-file notes.md                # 批量导入（每行一条 URL，行内其余内容为备注）
uv run aipulse inbox list                             # 查看已投喂条目

uv run aipulse knowledge items --query "agent"        # M6c：列出可记笔记的条目（item_id / 标题 / URL / 板块 / 日期）
uv run aipulse knowledge note --url "<URL>" --note "..."   # 写 / 覆盖笔记；传空字符串即清空
uv run aipulse knowledge mark --url "<URL>" --status read  # 阅读状态：read | unread | skipped
uv run aipulse knowledge list                         # 按 updated_at 倒序
uv run aipulse knowledge export                       # → data/knowledge/{index.md,my-notes.md,topics/*.md}

uv run aipulse trend --range 7d                       # M5：7 节分段生成周报 → data/reports/trend/weekly.md（需 key，7 次调用）
uv run aipulse trend --segments rising_topics,watchlist  # 只跑指定段（调试；段名见 reasoning/trend.py::SEGMENTS）
uv run aipulse trend --json --out /tmp/weekly.md      # 分段指标 JSON / 指定落盘；--max-tokens 覆盖每段输出上限
uv run aipulse selfcheck                              # L1–L4 离线自验证 → data/reports/trend/selfcheck.{md,json}（零 LLM）
uv run aipulse selfcheck --file <weekly.md> --no-write-state  # 只读检查，不更新 watchlist/calibration
```
```bash
# 自动化（需要 gh 已登录；daily.yml 也可在 Actions 页面手动触发）
gh workflow run daily.yml && gh run list --workflow=daily.yml
scripts/cron_daily.sh                                 # 本地 cron 备份（日志 → data/logs/cron.log）
```

`analyze` / `brief` / `daily` 都支持 `--date YYYY-MM-DD`（默认 `today`，按 `app.timezone` 取本地日）、`--db <path>`、`--json`；`brief` / `daily` 的 `--skip-llm` 与 `--no-llm` 等价，强制本次按 `off` 档跑。`predict` 同样支持 `--date` / `--db` / `--json` / `--skip-llm`：既可单独跑，`daily` 在 hybrid/full 档也会经 `_generate_daily_predictions()` 调它生成当日预言（off 档空转）；`prediction_id` 是稳定的，同一天重复跑不会重复入库。

产物落盘：`data/reports/YYYY/MM/DD/` 下 **8 个文件**（全部走 `FileNotifier`，§11.1）：
`brief.md` / `daily.json` / `meta.json` / **`scoreboard.md`（v1.10：daily 自动产出记分板）** / **`verdicts.md`（本次到期验证结果）** / **`predictions.md`（当日新生成的预言，被校验器拒收的草案也列出）** / **`signals.json`（指标快照 + 增速，Actions 无持久化时的跨天佐证）** / **`source_runs.json`（v1.19：每个源的 status/item_count/起止时间/error，含 `skipped_offline`）**。
`meta.json` 里额外有 `predictions` / `prediction_generation` / `brief` / `signals` / `verify` / `collect` 摘要块；M6b 起还会把 `enhance_total` / `enhanced` / `enhance_skipped_count` / `enhance_cache_hit` / `enhance_cost_cny` 提到顶层，用于跨天核对增强覆盖率与花费。注意 `analysis.new_entity_mention_rows` 是**本次运行新增的实体提及行数**（同日重复提及已去重），不是当日实体总数。

`data/` 布局（均在 `app.data_dir` 下）：

| 路径 | 内容 | 入库？ |
|---|---|---|
| `aipulse.db` | 主库（items / signals / topics / entities / predictions / … 共 10 表） | ✗（`.gitignore` 的 `data/*.db`） |
| `user_data.db` | M6c 用户知识库（笔记 / 阅读状态），固定顶层，`create_all` 建表不走 alembic | ✗（同上） |
| `cache/http.sqlite` | `utils/http.py` 的响应缓存 | ✗（`data/cache/`） |
| `inbox/` | 手动投喂的 `*.md` | ✗（从未跟踪，本地工作区） |
| `logs/` | cron 等日志 | ✗（`data/logs/`） |
| `knowledge/` | `knowledge export` 产物（`index.md` / `my-notes.md` / `topics/*.md`） | ✗（`data/knowledge/`） |
| `reports/YYYY/MM/DD/` | 每日报告，一天一个目录、**8 个文件**（早期 10-15/10-16 只有 7 个，尚无 `source_runs.json`） | **✓ 唯一入库的日报数据** |
| `reports/trend/` | 周报 `weekly.md` + 自检 `selfcheck.{md,json}` + 跨期状态 `watchlist.json` / `calibration.json`（M5） | **✓ 入库**（下期自检要读上一期状态） |

`data/reports/**` 是仓库里**唯一**公开的数据源；`.db` / 缓存 / 导出物一律不入库。判断"数据在哪"时先看这张表。

手动投喂两条路：① `aipulse inbox add <url> --note "..."` / `aipulse inbox add-file <path>`（CLI 直接入库）；② 往 `data/inbox/*.md` 里写（每行一条 URL，行内其余内容当备注），常规采集 `collect --sources inbox` 自动扫描。**抓不到标题也保留条目**（标题退化为 URL）——这是 v1.1"外网全断仍能走完整链路"的兜底契约。

### 测试 / 质量门禁

CI（`.github/workflows/ci.yml`，无 secrets）实际只跑 4 步：`ruff check .` → `ruff format --check .` → `mypy src/aipulse` → `pytest`（**没有覆盖率门禁**，覆盖率是本地基线，不达标不会挂 CI）。`.github/workflows/probe.yml` 是手动触发的探测，不在 CI 链上。

```bash
uv run pytest                             # 全量（当前 498 条，约 65s，无需网络、无需密钥）
uv run pytest tests/unit/test_dedup.py                      # 单文件
uv run pytest "tests/unit/test_dedup.py::test_l2_merges_arxiv_and_hf_same_paper" -q  # 单用例
uv run pytest -k "dedup or cluster" -q                      # 按关键字筛（跨文件，最常用）
uv run pytest -q --cov=aipulse --cov-report=term            # 覆盖率：collectors/ ≥80%、openai_compat ≥80%、TOTAL 90%

uv run ruff check .                       # lint（line-length=100，select=E,F,I,UP,B,SIM）
uv run ruff format --check .              # 格式检查
uv run mypy src/aipulse                   # strict；migrations 目录已排除

uv run pre-commit install                 # 钩子：ruff --fix + ruff-format + mypy + pytest
```

### 改哪里 → 先跑什么

改完别只跑全量再猜哪里挂了；按改动位置挑一行先跑（全量 60s，局部通常 <5s）：

| 改动位置 | 先跑 |
|---|---|
| `collectors/` · `configs/sources.yaml` | `uv run python scripts/probe_sources.py`（新 URL 必跑）+ `pytest tests/unit/test_collectors_parse.py tests/unit/test_collectors_runtime.py tests/integration/test_fixtures.py` |
| `normalize/` · `core/hashing.py` | `pytest tests/unit/test_dedup.py tests/unit/test_hashing.py` |
| `analysis/score.py` · `configs/scoring.yaml` | `pytest tests/unit/test_score.py`（纯函数，直接构造 `Item`） |
| `analysis/cluster.py` · `analysis/entities.py` · `analysis/signals.py` | 对应 `test_cluster.py` / `test_entities.py` / `test_signals.py` |
| `analysis/stats.py` · `render/scoreboard.py` | `pytest tests/unit/test_stats.py tests/unit/test_web.py`（校准曲线在 web 侧） |
| `reasoning/predictor.py` · `schema/prediction.py` · `prompts/predict/generate.j2` | `pytest tests/unit/test_prediction_schema.py tests/unit/test_predictor.py tests/unit/test_predict_cli.py` |
| `reasoning/verifier.py` · `reasoning/criteria.py` · `prompts/predict/verify.j2` | `pytest tests/unit/test_verifier.py tests/unit/test_criteria_verdicts.py tests/unit/test_predict_verify_cli.py` |
| `reasoning/brief.py` · `prompts/brief/*.j2` | `pytest tests/unit/test_brief.py tests/unit/test_brief_enhance.py` |
| `pipeline/collect.py` · `pipeline/daily.py` | `pytest tests/unit/test_pipeline_collect.py tests/unit/test_daily.py` |
| `web/` | `pytest tests/unit/test_web.py`（含 `mode=ro` 只读断言） |
| `knowledge/` · `cli/commands/knowledge.py` | `pytest tests/unit/test_knowledge_store.py tests/unit/test_knowledge_cli.py tests/unit/test_daily_index.py tests/unit/test_export.py` |
| `analysis/cross_period.py` | `pytest tests/unit/test_cross_period.py`（轨迹 / 9 结构 / 坏日归因 / 同构区间；改结构口径必补例） |
| `reasoning/trend.py` · `schema/trend.py` · `prompts/trend/*.j2` | `pytest tests/unit/test_trend.py tests/unit/test_selfcheck.py`；改 prompt 后**必须配 key 实跑一次** `aipulse trend --range 7d` |
| `reasoning/selfcheck.py` | `pytest tests/unit/test_selfcheck.py`（L1–L4 各有用例；状态文件用 tmp_path） |
| `llm/` | `pytest tests/unit/test_llm.py tests/unit/test_openai_compat.py`（`respx` 拦截 `/chat/completions`） |
| `store/models.py` | `uv run alembic revision --autogenerate -m "..."`（**只改模型不生成迁移 = 线上漂移**）+ `test_store.py` / `test_repo_items.py` |
| `core/config.py` · `configs/default.yaml` | `pytest tests/unit/test_config.py` |
| 任何 `cli/commands/*` | `pytest tests/unit/test_cli.py` + 该命令自己的测试 |
| **任何涉及 LLM 路径的改动** | **上面全绿也不算数**——配 key 实跑 `uv run aipulse daily`（见文首「开工前必读」） |

`mypy` 为全局 `strict = true`，但对 `aipulse.cli.*` / `aipulse.collectors.*` / `aipulse.pipeline.*` / `aipulse.web.*` 关闭了 `disallow_untyped_defs` 与 `disallow_untyped_calls`。`core/` `schema/` `analysis/` 必须完整通过 strict。

`pyproject.toml` 的 ruff per-file-ignores 里 `tests/* = ["S101"]` 是**当前无效的配置**（`S` 不在 `select` 列表里，只为将来开 `S` 规则预留）——不要以为项目已经在跑 bandit 类检查，也不要当冗余删掉。

### 数据源探测（M0 产物，需要联网；加源或改 URL 前必跑）

```bash
uv run python scripts/probe_sources.py                 # 5 个 API 源 + 全部 RSS feed
uv run python scripts/probe_sources.py --only rss      # 只探 RSS
uv run python scripts/probe_sources.py --no-cache      # 跳过 SQLite 响应缓存（排查坏响应时必用）
# 其他参数：--timeout / --connect-timeout / --retries / --out
```

本地探测不到的源，用 `.github/workflows/probe.yml`（`workflow_dispatch`，可选 `only: all|api|rss`）在 Actions 环境复测，下载 `fixtures-<run_id>` artifact 补进 `tests/fixtures/`。

### 数据库迁移

```bash
uv run alembic revision --autogenerate -m "说明"      # script_location = src/aipulse/store/migrations
uv run alembic upgrade head                            # 正式建表/演进走 alembic
```

`store/db.py::ensure_schema()` 会在库或 `items` 表缺失时自动 `upgrade head`（alembic.ini 缺失时退化为 `create_all`），pipeline 直跑入口已内置，不要绕过它手写建表。

当前迁移链（7 个，head = `f1a2b3c4d5e6`）：`85f7b6d0e84d` init_schema → `8db72036d522` add_items_skip_cluster → `a3c1d9f2e07b` add_llm_usage_error → `c4e8b1a72f90` add_items_last_seen_at → `d5a2c9b81e34` add_items_first_seen_at（存量均用 `collected_at` 回填）→ `e6b2f7c1a9d4` add_item_enhance（M6b 条目增强缓存）→ `f1a2b3c4d5e6` items_seen_at_not_null（SQLite batch 重建 `items`，把两列收紧为非空、消除 alembic 漂移）。

窗口过滤按 `configs/sources.yaml::time_semantics` 三态分流：`event`=published_at（HN/RSS）、`state`=last_seen_at（Trending）、`discovery`=first_seen_at（arXiv/HF，索引滞后）。

---

## 架构：一条数据穿过七层

```
configs/*.yaml ──> collectors/ ──> RawItem ──> normalize/dedup ──> store/repo_items ──> SQLite
      │                  │                          │                     │          │
   core/config      utils/http              pipeline/collect        store/models    │（读回）
  （YAML+${ENV}）  （限速/重试/缓存）        （编排 + 故障隔离）      （SQLModel 9 表）  ▼
                                                              analysis/（打分·聚类·实体，纯算法）
                                                                        │
                                              reasoning/brief.py（简报）· reasoning/predictor.py（预言）
                                                                        │  llm/（NullLLM | OpenAICompat，httpx 直连）
                                                          render/{markdown,json_out}.py
                                                                        │
                                                          notify/file.py → data/reports/YYYY/MM/DD/
```

四条编排链，CLI（`typer`）是唯一横向入口：

- M1：`pipeline/collect.py::run_collect()`（`asyncio.gather` + 并发信号量，单源隔离）。
- M2：`pipeline/daily.py::run_daily()` = collect → `analyze_day()`（打分/聚类/实体落库）→ `generate_brief()` → `render` → `FileNotifier`。`analyze` 与 `brief` 两个 CLI 分别只跑其中一段（`brief` 不采集也不做分析，直接读库）。
- M3a：`reasoning/predictor.py::generate_predictions()`（`aipulse predict` 可单独触发；`daily` 在 hybrid/full 档也会经 `_generate_daily_predictions()` 调用它，off 档空转）→ 硬校验 → `store/repo_predictions.py` 落库。手写预言走 `predict add`，不经 LLM 编排。
- M3b：`reasoning/verifier.py::verify_due_predictions()`（`predict verify` + `daily` 的 `auto_verify` 钩子）→ 量化判据查表 / 语义证据门槛+LLM → 写回 `predictions.status/verdict*`；`analysis/stats.py` + `render/scoreboard.py` 出记分板。

采集器之间不互相调用，只通过 `RawItem` 与编排层通信；`reasoning/` 只依赖 `llm.LLMClient` Protocol，不 import 具体 SDK。

### 模块职责

| 路径 | 职责 |
|---|---|
| `core/config.py` | `Settings` / `SourcesConfig` / `SourceConfig` / `FeedConfig`。YAML 为主，`${VAR}` / `${VAR:-default}` 插值，`AIPULSE__` 嵌套环境变量覆盖。`load_settings` 有 `lru_cache`，`load_sources` 无缓存（可运行时重载）。`project_root()` 可用 `AIPULSE_ROOT` 覆盖 |
| `core/timeutil.py` | 时间唯一来源。`utcnow()` / `ensure_utc()` / `parse_duration()` / `window_since()` / `day_window()` |
| `core/hashing.py` | `canonical_url`（去追踪参数；**arxiv.org 与 huggingface.co/papers 都归一成 `arxiv:{id}`**）/ `cross_source_key`（`arxiv:{id}`、`repo:{owner/name}`）/ `content_hash`(sha1) / `simhash64` + `hamming_distance`（中文按 bigram 分词） |
| `core/errors.py` | `AipulseError` → `CollectorError` / `LLMError` / `ConfigError` / `StoreError` |
| `core/logging.py` | structlog。`get_logger(__name__)`；支持把日志改道 stderr（`configure_logging(console_stderr=True)`），供 `--json` 输出保持 stdout 纯净 |
| `utils/http.py` | **所有网络请求的唯一出口**。每源独立令牌桶限速（`rate_limit: "3/s"`）、tenacity 重试（429/5xx/超时/`DecodingError`）、SQLite 响应缓存、统一 UA、代理解析（`HTTPS_PROXY`>…）。`respx` 在此拦截 |
| `schema/items.py` | `SourceEnum`（源白名单）/ `RawItem` / `SourceMetrics` |
| `collectors/base.py` | `BaseCollector`：子类只实现 `async fetch(since, until)`，可选 `healthcheck_url()`。辅助 `self.extra(key, default)` 读源特有配置、`self.raise_error()` 抛 `CollectorError` |
| `collectors/registry.py` | 按名注册 + `select()` 按 `enabled` / `availability` 过滤，返回 `(collectors, skipped)` |
| `normalize/clean.py` | `strip_html` / `normalize_whitespace` / `clean_text` / `truncate` / `detect_language`（只分 zh/en/None） |
| `normalize/dedup.py` | 三级去重（见下） |
| `store/models.py` | 10 张表：`items` / `signals` / `topics` / `entities` / `predictions` / `source_runs` / `pipeline_runs` / `llm_usage` / `llm_cache` / **`item_enhance`**（M6b 条目增强缓存，PK=item_id）。JSON 字段用 `sa_column=Column(JSON)`，不手写 `json.dumps` |
| `store/repo_items.py` | `upsert_items` / `write_signals` / `list_items_collected`（当日窗口）/ `apply_hot_scores` / `apply_topic_ids` / `upsert_topics` / `upsert_entities` / `list_topics` / `list_entities` / `list_signals`（全量）/ `topic_uid` |
| `store/repo_predictions.py` | `prediction_id`（`pred_` + `short_hash(day:statement:origin)`，稳定 id → `predict` 幂等）/ `insert_predictions`（已存在即跳过）/ `list_predictions` / `list_pending_due` / `list_verified_since`（`verdicts.md` 用）/ `save_verdict` |
| `store/repo_runs.py` | `record_pipeline_run()`：写 `pipeline_runs`（stage=`daily`） |
| `store/db.py` | `engine_for` / `init_db` / `session_for` / `ensure_schema`；**`readonly_engine_for()`**：SQLite `mode=ro` 打开主库，知识库等旁路不得写主库 |
| `knowledge/models.py` | 独立用户库表：`knowledge_items`（item_id PK / status / note / tags / topic_id / created_at / updated_at）+ `schema_version`。独立 `USER_METADATA`，`create_all` 不会创建主库表 |
| `knowledge/store.py` | `user_db_path()`（固定 `data/user_data.db`）/ `init_user_db()`（create_all + schema_version，不走 alembic）/ `user_session_for()` / `KnowledgeStore`（`get` / `all` / `list` / `upsert` / `set_status` / `set_note`）。所有写操作只碰 user_data.db |
| `knowledge/daily_index.py` | 扫描 `data/reports/**/daily.json`，构建 item / url / title 索引；兼容 10-15/16 空 comments、10-17 `why_it_matters`、10-18 `why` 与字段缺失；跨天同 item 优先保留有 why 的记录 |
| `knowledge/export.py` | `Exporter` Protocol + `MarkdownExporter`；ExportItem 组装、skipped 过滤、板块 slug + 500 条/200KB 分片、`index.md` / `my-notes.md` / `topics/*.md`、幂等 |
| `cli/commands/knowledge.py` | `knowledge mark` / `note` / `items` / `list` / `export`；`item_id` / `--url` / `--query` 三选一；索引外 item_id 需 `--allow-unknown`；笔记只写 user_data.db |
| `analysis/signals.py` | `velocity_for_item()`：由 `signals` 历史算 Δmetric/Δhour，无历史返回 `None`；`build_signals_summary()`：按实体聚合**全量历史**成 `signals.json`（含 `status` / `delta` / `velocity_per_hour` / `velocity_24h`）；`trending_streak_days()`：连续在榜天数（M6a）；**`repo_star_snapshots()` / `velocity_board()`：star 总数与绝对增量、增速榜（v1.19，纯函数；取 lookback 窗口首末，不取全表首末；榜单按日均增量排序、显示绝对增量 + 窗口）**。**增速口径：两次快照间隔 < `signals.min_velocity_window_hours`（默认 6h）标 `insufficient` 且不给数字**，<2 个快照标 `cold_start`。`signals` 表的正确列名是 `entity_type` / `entity_key` / `metric` / `value` / `ts` |
| `analysis/score.py` | 热度打分（见下节）。`compute_hot_scores()` 是纯函数（可脱离 DB 单测），`score_items()` 才碰库 |
| `analysis/cluster.py` | jieba + TF-IDF + 余弦 → 连通分量聚类；排除 `skip_cluster`；单点簇不落库 |
| `analysis/entities.py` | 词典 + 正则抽实体（`configs/entities.yaml` 驱动，加实体不改代码），`matcher()` 按 `project_root()` 缓存；`count_entities()` 聚合同日实体频次 |
| `analysis/cross_period.py` | M5 跨期层（**纯计算，零 LLM，只读 `data/reports/**`**，不碰主库）：`load_cross_period()` 把日报解析成 `CrossPeriodIndex`（`DaySnapshot` 按天）→ `build_tracks()` 出条目轨迹 → `compute_all()` 按固定顺序算 **9 个结构**（`heat_migration` / `co_movement` / `divergence` / `substitution` / `emergence` / `persistence` / `source_share` / `prediction_review` / `unrealized`），任一算不出不影响其余。归因三件套是后续一切比较的前提：`collection_failures()` / `source_change_days()` / `homogeneous_segments(min_days=3)`——**跨坏日或跨源集合变更的比较都是假趋势** |
| `llm/base.py` | `LLMClient` Protocol + `NullLLM`（off 档零网络）+ `FakeLLM`（测试用）+ `build_client()`（按 `effective_mode()` 选实现，hybrid/full 才懒加载 `OpenAICompatClient`） |
| `llm/structured.py` | `generate_structured()`：response_model → JSON Schema → 校验 → **一次**修复重试 → 再失败返回 `None`（降级，绝不 raise 到 pipeline） |
| `llm/prompt.py` | 加载 `prompts/**.j2`，解析 front-matter（`model_tier` / `temperature` / `purpose`），`version_hash` = 全文 sha256 前 8 位 |
| `llm/openai_compat.py` | 唯一真实实现：**httpx 直连**（复用项目 `HttpClient`；`openai` SDK 已在 v1.7 移除，`uv.lock` 无 openai），fast/strong 双模型；`llm.json_schema: auto` 下首次 json_schema 收到 400 即降级 json_object + prompt 内嵌 schema，并进程内记忆（降级原因写 `llm_usage.error`，迁移 `a3c1d9f2e07b`） |
| `llm/cache.py` / `llm/budget.py` | `llm_cache` 表缓存 / 每日预算（`budget.daily_limit_cny`）与降级顺序 |
| `reasoning/brief.py` | `generate_brief()`：Top N 上下文组装（token 预算裁剪）→ LLM → 失败降级为 `_data_brief()` 数据版。**M6b**：`_render_ids()` 取渲染集 → `_enhance_comments()` 条目级缓存（`content_hash` + 双 prompt 版本 + TTL + 热度差）→ 分批调 `item_comment` / `item_enhance`，写 `item_enhance` 表；off 只读 / hybrid 补缺 / full 全刷 |
| `reasoning/predictor.py` | `generate_predictions()`：Top N + 主题 + 实体频次组装上下文 → `prompts/predict/generate.j2` → 结构化 `PredictionBatch` → 硬校验 → **一次**语义重写 → 仍不合法丢弃记账（任何 LLM 异常都降级为空，绝不 raise 到 pipeline） |
| `reasoning/criteria.py` | 量化判据模板库（`configs/criteria.yaml`）的加载/渲染：`criteria_names` / `render_criteria` / `coerce_param` / `parse_param_assignments`。M3b 的 verifier 将复用同一套模板定义 |
| `schema/trend.py` | `TrendSegment`（key/title/body/char_count/cited_item_ids/boilerplate_hits/violations/token 与花费）+ `TrendReport`（窗口 + **比较区间** `comparison_*` / `truncated_segments` / `cost_cny`）。每段自带违规与截断记账，`--json` 直接吐它 |
| `schema/prediction.py` | `Prediction` / `PredictionBatch` / `Verdict` + `find_vague_phrases`（模糊措辞黑名单，"可能"用负向断言排除"不可能"）+ `validate_prediction`（可证伪红线校验） |
| `reasoning/verifier.py` | M3b 到期验证：**双路径**——`judge_criteria()` 量化判据查表（6 模板 + `custom` 受限 AST 求值，**零 LLM**）/ 语义路径 `retrieve_evidence()`（TF-IDF+余弦，窗口 `[生成日, due_date+3]`）→ 充分度门槛 → `generate_structured(Verdict)`。`verify_due_predictions()` 编排；**unverifiable 只由证据门槛产生**，LLM 失败保持 pending |
| `reasoning/trend.py` | M5 生成层：`build_evidence()` 把 9 个结构 + 轨迹压成**每节独立证据包**（≤200 字/条、合计 ≤15 条，含 `item_id`），`generate_trend()` 按 `SEGMENTS` 7 节**每段一次 strong 调用**串行生成（段名见常量：`rising_topics` / `falling_topics` / `emerging_topics` / `structural_changes` / `second_order_effects` / `prediction_review` / `watchlist`），逐段走 `segment_violations()` 校验字数与套话后落 `TrendReport`，**单段失败只跳该段**。`SEGMENT_MAX_CHARS` 是硬上限，`WORD_BUDGET` 是 prompt 里的软区间 |
| `reasoning/selfcheck.py` | M5 验证层（**离线零成本**）：`parse_markdown()` 回读 `weekly.md` → `check_l1` 硬判据（结构/字数/cited id 存在性）→ `check_l2` 信息增量（对比基线 Top，防复述日报）→ `check_l3` 跨期回检（`watchlist.json` 对照上期）→ `check_l4` 校准（`calibration.json`）；`run_selfcheck()` 汇总，任一层 FAIL 则 `selfcheck` 退出码 1 |
| `analysis/stats.py` | `compute_prediction_stats()`：命中率 / 加权分 / Brier（`partial=0.5`）/ 校准分桶（含 `[0.05,0.5)`）/ 按 category·horizon·origin·model·prompt_version 分组；`unverifiable`+`pending` 不入分母 |
| `render/scoreboard.py` | `render_scoreboard_markdown()`：可直接贴 README 的预言记分板（总览 + 校准表 + 分组），0 样本时优雅空态 |
| `render/markdown.py` / `render/json_out.py` | 简报渲染；`brief.md` / `daily.json` |
| `render/verdicts.py` | `render_verdicts_markdown()`：当日到期验证结果 → `verdicts.md`（命中/部分/落空/无法验证 + 判定方 + 依据）|
| `render/predictions.py` | `render_predictions_markdown()`：当日**新生成**的预言 → `predictions.md`；被校验器拒收的草案也一并列出（拒收理由是质量证据，不藏）|
| `pipeline/collect.py` | `run_collect()`：`asyncio.gather` + 并发信号量（默认 6），每源独立 `try/except`，写 `source_runs`，落库前去重 |
| `pipeline/daily.py` | `run_daily()` / `analyze_day()` / `report_dir_for()`：每日一条龙编排。`_generate_daily_predictions()` 在 hybrid/full 档生成当日预言并入库（异常只记 meta，不拖垮日报）；随后产出 `predictions.md` / `scoreboard.md` / `verdicts.md` / `signals.json`，并把 `predictions`（`_stats_digest`）/ `prediction_generation` / `signals` 写进 `meta.json` |
| `notify/base.py` | `Notifier` Protocol + `RenderedReport`；`notify/file.py::FileNotifier`（唯一实现）。其余渠道明确 `NotImplementedError` |
| `utils/text.py` | `estimate_tokens`（中文 1 字 1 token / 英文 3.5 字符）+ `truncate_summary(≤300)` |
| `web/app.py` | M4 只读看板：`create_app()`，5 个页面（`/` `/archive` `/predictions` `/topics` `/search`）+ HTMX 局部刷新 `/search/partial`；「趋势」「辩论」入口置灰占位（M5 点亮）。测试可注入 `db_path` / `reports_dir` |
| `web/data.py` | `ReadOnlyStore`（SQLite **`mode=ro`** 只读 + `available` 判存在）/ `ReportIndex`（扫 `data/reports/*/*/*/daily.json`）。库不存在时不创建、查询返回空，页面走空态 |
| `web/charts.py` | `build_calibration_chart()`：校准分桶 → SVG 坐标（纯函数）。对角虚线 = 完美校准 |
| `web/templates/` · `web/static/` | Jinja2 模板（base/index/archive/predictions/topics/search/_results）+ 极简黑白样式（无前端构建链）。**htmx 1.9.12 已收进 `static/htmx.min.js`（不走 CDN）**，且只做渐进增强——脚本没加载时搜索表单退化为普通 GET |

### 采集编排的三条状态语义

`source_runs.status` 的取值决定了"要不要报红"，不要混用：

- `ok` / `degraded`：有条目 / 源无条目或 optional 子源失败。**都不算失败。**
- `failed`：源级故障，记 `error`，但该源被隔离，其余源照常。
- `skipped_offline`：`actions_only` 的源在本地被跳过。**不计失败、不影响退出码。**
- `skipped_disabled`：配置里 `enabled: false`。

`aipulse collect` 无论单源是否失败都 `raise typer.Exit(code=0)`——这是故障隔离对外契约的一部分，不要"顺手"改成非零退出码。

### 三级去重（写库前统一做一次）

| 级别 | 方法 | 效果 |
|---|---|---|
| L1 | `sha1(canonical_url + source)` | 同源自 URL 丢弃 |
| L2 | `cross_source_key`：`arxiv:{id}` / `repo:{owner/name}` | 跨源合并成一条，`seen_in` 记录多源 |
| L3 | `simhash64(title + summary)`，汉明距离 ≤ 3 | 近似事件合并 |

合并规则：最早 `published_at` 为主体、各项指标取最大（**缺失填 `None`，不用 `0` 覆盖真实值**）、tags 并集、`seen_in` 并集、保留最长摘要。跨源时写 `extra["cross_source"]=True` + `extra["cross_source_bonus"]=0.05`（M2 打分层消费）。

存储层再保证一次：`Item.id` = `_PREFIX + content_hash(cross_source_key or url)[:16]`，**源无关**——这是"arXiv 与 HF 同一篇论文永远落在同一行"的落地方式，跨源后 `seen_in` 累加。

### M2 分析层：热度 / 聚类 / 实体 / 简报

**热度公式**（`analysis/score.py`，权重全部读 `configs/scoring.yaml`，改配置不改代码）：

```
hot_score = 100 * clamp( w_engagement*engagement_norm        # Σ coeff*log1p(metric)，源内分位归一化
                       + w_freshness *exp(-max(0,age_h-grace)/tau)
                       + w_velocity  *velocity_norm          # Δmetric/Δh，源内分位
                       + w_source    *source_weight          # sources.yaml 静态权重
                       + 0.05*(len(seen_in)-1) )             # 跨源印证加成，每个额外源 +5 分
```

三条容易踩的语义：engagement 与 velocity **只在源内**归一化（不可跨源比）；某源一条 velocity 都算不出时用 `cold_start.velocity_neutral` 兜底并打 warning；**全零 engagement 的源（rss / inbox）直接归 0**，不做分位归一化——否则无信号维度会被中性值凭空抬高热度。

**聚类**（`analysis/cluster.py`）：中文 jieba 分词、英文按词切；`skip_cluster=True`（title_only，如量子位 22 字摘要）**不进相似度矩阵**；余弦 ≥ `cluster.similarity_threshold`（0.35）建边 → 连通分量即主题；成员数 < `min_cluster_size`（2）不落库；代表条目 = 簇内 hot_score 最高者，keywords = TF-IDF top-5，name = top-3 拼接。

**实体**（`analysis/entities.py`）：词典 + 正则，词典在 `configs/entities.yaml`（加实体 = 加一行），类型 = model/framework/company/hardware/concept/person。

**三档模式在 M2 的落地**：`off`（或无 key 自动降级）→ 注入 `NullLLM`，产出 `_data_brief()` 数据版简报，零网络；`hybrid` → daily_brief（主编点评）；`full` → 再加每条 item_comment。`--skip-llm` / `--no-llm` 强制当次走 off。**任何 LLM 失败（网络 / 结构化校验失败）都降级为数据版简报并置 `meta.degraded`，绝不中断流水线。**

### M3a 预言系统：生成 / 手写 / 不可证伪拦截

**生成链路**（`reasoning/predictor.py::generate_predictions()`）：当日 Top N + 主题 + 实体频次组装上下文（token 预算裁剪）→ `prompts/predict/generate.j2`（`model_tier: strong`）→ 结构化输出 `PredictionBatch` → 硬校验 → 不合法触发**一次**语义重写（把问题回传要求只重出合法 JSON）→ 仍不合法则丢弃并写 `meta["dropped"]`。off 档 / `--skip-llm` 直接返回空（手写才是 off 档核心）。

**可证伪红线**（`schema/prediction.py::validate_prediction`，违反即拒收）：`falsifiable_criteria` 非空是**硬性必填**；`statement` 命中模糊措辞黑名单（"可能/也许/或许/未来可期/值得期待/值得关注/有望/或将/大概率/早晚/迟早"，"可能"用负向断言排除"不可能"）即拦截；`confidence` 必须是 0.05 的整数倍且 ∈[0.05, 0.95]；`horizon_days ∈ {7,30,90,180}`；`category ∈ {capability,product,research,business,policy,hardware,community}`；**LLM 生成要求证据 ≥2 条**（`require_evidence=True`），手写预言不强求证据（§11.4）。

**两种来源**（`origin`）：`llm` 走自动生成（hybrid/full 档；off 档空转）；`human` 走 `aipulse predict add`（**全档位核心**）——「参数 + 缺参自动降级为交互式向导」：传 `--criteria` 判据模板则 `falsifiable_criteria` 自动渲染（如 `github_stars_reach(repo='…', threshold=90000)`），缺必填参数用 `rich.prompt` 追问；不设模板则追问一句话判据；末尾预览卡片 + 二次确认，`--yes` 跳过。

**幂等**：`prediction_id = pred_ + short_hash(day:statement:origin)`，同一天同一句话重复跑不会刷出重复行（`insert_predictions` 遇已存在 id 跳过，不覆盖人工已 review 的记录）。

**判据模板库**（`configs/criteria.yaml`，加模板不改代码）：github_new_repo / github_stars_reach / hn_story_points / entity_mentions / arxiv_paper_count / custom——到期时**查库即判、零 API 成本**（M3b 实现判定）。

**本阶段边界（M3a 视角，已由 M3b 补全）**：M3a 只做生成 / 手写；`predict verify` / `predict review` / `stats` 由 M3b 实现。

### M3b 到期验证与统计（★ 闭环）

**双路径**（`reasoning/verifier.py`）：`criteria` 非空 → `judge_criteria()` 查 `signals`/`entities`/`items` **直接判定，零 LLM**（6 模板 + `custom` 受限 AST 求值，见 `configs/criteria.yaml`）；`criteria` 为空 → `retrieve_evidence()`（TF-IDF 余弦，窗口 `[生成日, due_date + evidence_window_grace_days]`，Top `evidence_top_k`）→ 证据充分度门槛（`≥min_evidence` 条过阈值 或 单条 `≥strong_similarity`）→ 达标才调 `prompts/predict/verify.j2` 出 `hit/partial/miss`。

**不可逾越的红线（v1.9）**：`unverifiable` **只由系统的证据门槛产生**（写在 `status`，**不是** `verdict`；`Verdict` 保持 3 值），LLM 不得输出——否则它会变成逃避 miss 的软出口。证据不足**不调 LLM**：`today ≤ due_date + grace_days` 保持 `pending` 重试，超期转 `unverifiable`；**LLM 失败保持 `pending`，绝不当 miss**；`miss` 的前提是"证据覆盖已充分"（查不到 ≠ 没发生）。`partial` 高度克制（仅多子条件部分满足 / 阈值容差带，默认 5%）。

**人工兜底**：`predict review <id> --verdict --note` 写 `verified_by='human'`，可覆盖 auto 结果，**同样计入统计**。

**统计口径**（`analysis/stats.py`，v1.9）：`unverifiable`/`pending` **不入分母**；命中率 = hits/已验证；加权分 = `mean(verdict_score)`；Brier = `mean((confidence − verdict_score)²)`（`partial` 按 0.5）；校准分桶 `[0.05,0.5) / 0.5-0.6 / 0.6-0.7 / 0.7-0.8 / 0.8+`；记分板 Markdown 由 `render/scoreboard.py` 生成（0 样本优雅空态）。

**编排接入**：`pipeline/daily.py` 在 brief 之后按 `pipeline.auto_verify` 调 `_auto_verify()`（异常只降级写 meta，绝不拖垮日报）。off 档下量化判据可完成"生成→到期→自动验证→记分板"全闭环，零 LLM。

### M5 周期趋势：S1 → S5（长文 / 自验证 / 辩论 / 可读化，全部已跑通）

```
data/reports/**/daily.json ──> analysis/cross_period（纯计算，零 LLM）
      │  load_cross_period → CrossPeriodIndex → build_tracks → compute_all（9 结构 + 归因）
      ▼
reasoning/trend.build_evidence()   ← 证据带 attribution / masked_days / 同构比较区间
      │  每节独立证据包（≤200 字/条，合计 ≤15 条，带 item_id）
      ▼  generate_trend()：7 节 × 每节 1 次 strong 调用，逐段校验
data/reports/trend/weekly.md ──> reasoning/selfcheck（L1–L4，离线零成本）
      │
      ▼
selfcheck.{md,json} + watchlist.json / calibration.json（下期 L3/L4 回读）
```

三条读图要点：① **数据入口是已 commit 的日报 JSON，不是主库**——M5 全程不碰 `aipulse.db`，也读不到 db 里才有字段；② LLM 只负责解释 `cross_period` 算出的结构，**不负责"发现趋势"**（让模型自由挑的路子已被 M6b 与 M5 各证伪一次）；③ `trend` 目前只能手动/CI 触发（`pipeline/weekly.py` 不存在），`daily` 不会自动跑周报。

---

## 配置与环境

三档运行模式（`configs/default.yaml` 的 `mode`，仓库默认 `full`）：`off`（零 API 花费）/ `hybrid`（预言生成 + 主编点评）/ `full`（全部，M5 后叠加长文与辩论）。`Settings.effective_mode()` 在 `llm.enabled=false` 或 `api_key` 为空时**自动降级为 `off`**，只提示一次，不报错退出。

**daily 与三档的关系（M4 补齐）**：`daily` 会按档位做 `brief`（hybrid/full → 主编点评）**和 `generate_predictions`（hybrid/full → 当日预言入库）**，`off` 档两条路径都不触发（零网络）。daily.yml 里显式设了 `AIPULSE_MODE=hybrid`——**不设这个，配了 key 记分板样本也不会增长**。

**数据源环境分级（本地 WSL 与 Actions 网络可达性不同）**：

| `availability` | 本地（未设 `AIPULSE_ENV`） | Actions（`AIPULSE_ENV=actions`） |
|---|---|---|
| `always` | 正常采集，失败计入统计 | 正常采集 |
| `actions_only` | **跳过**，写 `skipped_offline`，不计失败 | 正常采集 |

当前 `hf_papers` / `reddit` 标 `actions_only`。**不要因为本地测不到就把源写死禁用，也不要把本地跳过当 bug 排查。**

环境变量：`.env` 由 `aipulse init` 从 `.env.example` 复制（不含真实密钥）。关键项：`AIPULSE_LLM__BASE_URL` / `AIPULSE_LLM__API_KEY`、`GITHUB_TOKEN`（GitHub Search API 30 req/min，无 token 只有 10）、`HF_TOKEN`、`HTTP(S)_PROXY`、`AIPULSE_ROOT`（测试指向临时目录）、`AIPULSE_ENV`。

`configs/sources.yaml` 的 `rate_limit` 是**必填**项，形状 `"N/period"`，period 支持 `s/m/h/d`（如 `3/s`、`10/1s`、`1/6h`）。

五份配置的分工（`core/config.py` 的 `load_settings` / `load_sources` / `load_scoring` / `load_entities` / `load_criteria`）：

| 文件 | 段 | 消费方 |
|---|---|---|
| `default.yaml` | `app` / `mode`（**必须是 `${AIPULSE_MODE:-full}` 占位符**，写死字面量会压掉环境变量）/ `llm`（`json_schema: auto`、`timeout_s`/`timeout_strong_s`、**`max_tokens_fast` 4000 / `max_tokens_strong` 10000**——reasoner 思维链会吃掉输出预算）/ `budget`（含 `price_*_cny_per_1m`）/ `pipeline`（`daily_top_n` `brief_sections` `predictions_per_day` `prediction_horizons`（默认 `[7,30,90]`，`180` 虽合法但未启用）**`predict_candidate_top_n`（20，候选池只给 id+标题）** `auto_verify` `weekly_debate_enabled`）/ **`brief`（`max_items_per_section` + `velocity_board_enabled` / `velocity_board_top_n` + M6b 增强六项：`enhance_top_n` 30 / `enhance_batch_size` 10 / `enhance_budget_cny` 0.15 / `enhance_ttl_days` 30 / `enhance_refresh_hot_delta` 10.0 / `enhance_refresh_on_new_signals` false）** / `verify`（`grace_days` `evidence_window_grace_days` `evidence_top_k` `similarity_threshold` `strong_similarity` `min_evidence` `partial_tolerance` `max_context_tokens`）/ **`signals`（`min_velocity_window_hours` + `repo_lookback_days`，M4/v1.19）** / `output` / `notify` / `http` | `Settings` |
| `sources.yaml` | 每源的端点、权重、`availability`、`rate_limit`、`title_only`、`fallback_endpoints` | `collectors/` + `analysis/score.py` |
| `scoring.yaml` | `weights` / `freshness` / `cross_source_bonus` / `engagement`（每源指标系数）/ `cold_start` / `title_only_weight` / `cluster` | `analysis/score.py` `analysis/cluster.py` |
| `entities.yaml` | `entities.{model,framework,company,hardware,concept,person}`（name + aliases） | `analysis/entities.py` |
| `criteria.yaml` | `criteria.{name}`（`description` + `params[{name,type,required,default}]`，type ∈ str/int/float） | `reasoning/criteria.py`（`predict add` 向导 + M3b 验证） |

### ★ 分析窗口：collect 与 analyze 必须共用同一个窗口

`pipeline/daily.py` 里**只算一次** `window = window_since(since)`（滚动 24h，截至运行时刻），显式传给 `run_collect(window=...)` 与 `analyze_day(window=...)`，简报与预言取条目也用它。

**为什么**：曾经 collect 按 `--since 24h` 往前滚、analyze 按 `day_window(本地今天)` 切，两处独立计算。定时在 UTC 23:00（北京 07:00）跑，两个窗口只重叠约 7 小时——实测当天 `analysis.items = 1`，日报自称"过去 24 小时"却只覆盖 7 小时。cron 也据此改到 **UTC 00:00（北京 08:00 = 美西前一日 17:00）**：滚动 24h 刚好完整覆盖当日美国工作日，重要发布读到时不会滞后一天。

**代价（接受）**：日报跨两个自然日，所以 `meta.json` 有 `window`（含 `since_local` / `until_local` / `hours`），`brief.md` 顶部也标了"覆盖窗口"。改窗口逻辑前先看 `tests/unit/test_daily.py::test_daily_passes_one_window_to_both_collect_and_analyze`。

注意：窗口按 `collected_at` 过滤（不是 `published_at`）——语义是"本次运行采集到的条目"，窗口外的历史条目不会混进当天。

---

## 硬性约定（CI 与人工验收都会查）

### 必须停下来问项目负责人的四类事（v1.22）

1. **任何涉及“数据在哪里”的判断** —— `*.db` 不进仓库；公开数据只有 `data/reports/<date>/` 下已 commit 的文件。不要把本地库、缓存或未 commit 的报告当成公开数据源。
2. **任何“本地能不能跑”的结论** —— WSL 无外网 → 不能本地采集；导出/渲染不需要网络，可以本地跑。不要把“采集不可用”推广成“所有功能都不可用”。
3. **任何字段复用/新增** —— 先问是否已有字段能承担；不要直接加列、加表或造新字段。
4. **优先级排序** —— 用户点名的需求自动 P0；不要按自己的 roadmap 或“顺手优化”降级。

### 红线（v1.22；手册 §0.3 新增 44–47，实际条目到 47，标题暂仍写“四十三条”）

下面只列最常踩的 14 条；M6b 另有 5 条高频红线：**增强结果必须持久化**（`item_enhance`，不重复付费）、**只对 `brief.enhance_top_n` 的渲染集增强**、**中文条目不生成中文概述**、**why/stance 只由 `item_enhance.j2` 产出**（不得回显标题摘要、不得与 `item_comment.j2` 双写）、**增强失败只降级为 `—`，不拖垮日报**。另有时间语义三态、Actions 固定 `ubuntu-24.04`、star 只显示绝对增量等，见手册。

1. 不一次性生成整个项目——分阶段，DoD 全勾再进下一张卡。
2. **不凭想象写字段解析**——必须基于 `tests/fixtures/` 的真实响应快照。
3. **prompt 不写进 `.py`**——一律 `prompts/**.j2`，头部必须有 YAML front-matter（`model_tier` / `temperature` / `purpose`）。已实现：`brief/daily_brief.j2`、`brief/item_comment.j2`、`brief/item_enhance.j2`、`predict/generate.j2`、`predict/verify.j2`、`trend/weekly.j2`（M5）；`debate/` 仍为空，是 M5 下一半的落点。
4. LLM 输出不直接 `json.loads`——必须 response_model + 校验 + 一次修复重试 + 再失败降级跳过。
5. 单源异常不得导致整条流水线崩溃。
6. **不实现任何微信 / X（Twitter）相关的采集器、配置段、环境变量或 RSS 桥**——v1.1 已彻底移除，相关内容只能走 inbox 手动投喂（`aipulse inbox add` / `add-file`，或往 `data/inbox/*.md` 写 URL）。
7. 里程碑顺序不得搞反：**M4 = Actions 自动化 + Web 看板 + README 发布（先做）；M5 = 周期长文 + 多角色辩论（后做）**。
8. `mode: off` 下禁止发任何到模型服务商的网络请求——注入 `NullLLM`，单测用 `respx` 断言 0 次调用。
9. 现在不实现 OAuth / 邮件 / Telegram / 飞书推送——只留 `Notifier` Protocol 与 `mode: oauth` 配置项。
10. 未经 `scripts/probe_sources.py` 实测的 RSS URL 不得留在 `configs/sources.yaml`。
11. 手写预言必须是「参数缺失时自动降级为交互式向导」，不是纯参数也不是纯向导。
12. `actions_only` 源在本地的跳过**不是失败**。
13. 不把 `hf-mirror.com` 写进生产默认配置——只留 `fallback_endpoints: []` 空字段，由用户自行填写。
14. `title_only: true` 的中文源（量子位，摘要仅 22 字）**不参与 TF-IDF 聚类**，权重降至 0.35。

### 编码规范（`手册 §0.2`，CI 会检查）

- 类型注解：公开函数必须有完整注解；`mypy --strict` 至少对 `core/` `schema/` `analysis/` 通过。
- 异步：采集器 `async def fetch()`；pipeline 用 `asyncio.gather`；CLI 用 `asyncio.run`。
- 网络：采集器内**禁止**裸调 `httpx`，一律用注入的 `self.http`（限速/重试/缓存/代理/UA 统一，且测试才能用 `respx` 拦截）。
- 时间：代码内一律 UTC；**禁止 `datetime.now()`**，用 `core/timeutil.utcnow()`；源给的时间先 `ensure_utc`；只在渲染层转 `Asia/Shanghai`。
- 日志：`structlog.get_logger(__name__)`，**禁止 `print`**（CLI 输出用 `rich.console`；`scripts/*` 例外，已加 per-file-ignore `T201`）。
- 配置：**禁止硬编码常量**，权重 / 阈值 / 源配置全部走 `configs/*.yaml`。
- 注释：复杂算法（打分、聚类、去重、Brier）必须写中文注释解释**为什么**这么算。
- 提交：Conventional Commits（`feat(m1):` / `fix(m1):` / `docs(m0):` / `ci:` / `test(fixtures):`），每个阶段结束打 tag（`m0` / `m1` / …）。

### 采集器六条约定（`docs/新增数据源指南.md` §2.4）

1. 只用注入的 `self.http`。
2. 不写库、不去重、不调 LLM。
3. 空返回 → 返回 `[]` + `log.warning`，**不抛异常**（"今天没热点"不是故障）。
4. 网络/解析异常 → `raise self.raise_error(...)`，由编排层写 `source_runs.status='failed'` 后继续跑其他源。
5. 缺失字段填 `None`，**不要填 `0`**（`0` 会被打分公式当成真实数据污染排序）。
6. 部分失败要内部隔离（逐 feed / 逐 subreddit / 逐关键词），全部失败才算源级失败——参考 `rss.py`、`reddit.py`、`hackernews.py`。

新增数据源：**增删 RSS/Atom 源 = 改 `configs/sources.yaml` 的 `rss.feeds` 列表，无需命令、无需代码**（`sources` 子命令是占位，加源不依赖它）；新增全新类型源见 `docs/新增数据源指南.md`，才需要写 `BaseCollector` 子类 + 在 `registry.py` 注册。扩 `SourceEnum` 需同步改 3 处（枚举、`_DISPLAY_NAMES`、指南文档）——这是刻意的摩擦，先确认现有源 + RSS 覆盖不了。完整流程见 `docs/新增数据源指南.md`。

---

## 测试约定

- `asyncio_mode = "auto"`（无需给每个 async 用例加装饰器），`testpaths = ["tests"]`。
- **全部测试必须无需网络、无需密钥**（CI 无 secrets 且必须全绿）。HTTP 用 `respx` 拦截；`HttpClient` 构造时传 `cache_enabled=False`。
- `tests/conftest.py` 提供 `fixtures_dir` / `fixture_text()` / `fixture_bytes()` / `make_cfg()` / `make_feed()` / `make_http()`。
- 解析器测试是 **fixtures 驱动、先测试后实现**：先落真实响应到 `tests/fixtures/`，把 fixture 变成断言，再写解析代码。每个采集器至少 3 类用例：正常解析 / 边界（空、单条、窗口内无内容）/ 脏数据（缺字段、结构变更 → 不崩、不编造数据）。
- 运行时测试放 `tests/unit/test_collectors_runtime.py`（`respx` mock 抓取流程与降级路径）。
- `tests/integration/test_fixtures.py` 是 **fixtures 契约测试**：快照缺失时 `pytest.skip` 显式标出（**不得静默通过**），并断言每个源探测记录都有明确结论、失败源带错误信息。
- **测试统一用 30 天窗口**写断言——fixture 是冻结快照，用 `--since 24h` 会随时间流逝而失效。
- `collectors/` 覆盖率基线 ≥80%（当前 88%）。
- M2 分析层单测（`test_score.py` / `test_cluster.py` / `test_entities.py` / `test_signals.py`）走**纯函数**路线：直接构造 `Item` 调 `compute_hot_scores()` / `cluster_items()`，不依赖 DB。
- LLM 链路**可用 `respx` 拦截**：v1.7 起 `llm/openai_compat.py` 改 httpx 直连（走项目 `HttpClient`），`tests/unit/test_openai_compat.py` 即用 `respx` mock `/chat/completions` 与 json_schema→json_object 降级路径。结构化链路也仍可用桩客户端（`FakeLLM` / 自定义 `LLMClient`），off 档用 `NullLLM` 断言零网络。
- M3a 预言单测：`test_prediction_schema.py`（Pydantic 校验 / 模糊措辞）、`test_predictor.py`（生成 + 一次重写 + 丢弃记账）、`test_predict_cli.py`（`predict add` 双模交互 + 幂等）。
- M4 单测：`test_web.py`（`TestClient` 打 5 个页面 + **只读断言**：直接对看板 engine 发 DELETE 必须被 SQLite 拒绝；0 样本空态文案；报告 JSON 损坏时的降级；`serve` 用 monkeypatch 的假 `uvicorn.run` 验端口）、`test_signals.py`（`build_signals_summary` 的增速 / 冷启动 / 排序）、`test_verdicts_render.py`、`test_daily.py`（新增 `scoreboard.md`/`signals.json` 落盘与 meta 摘要）。
- M6b 单测：`test_brief_enhance.py`（缓存命中 0 次 LLM 调用 / prompt 版本失效 / TTL 过期 / full 档忽略缓存 / 单批失败不影响其他批 / 渲染集与板块切片一致）。
- M6c 单测：`test_knowledge_store.py`（用户库建表/CRUD/主库 checksum 三不变/只读守卫）、`test_knowledge_cli.py`（mark/note/items/list/export、URL/query 定位、候选不自动选、`--allow-unknown`）、`test_daily_index.py`（四种历史结构/why 优先合并/URL 查询）、`test_export.py`（协议/回退/501 条与 200KB 分片/幂等）。
- inbox CLI 单测（`test_inbox_cli.py`）：`add` 正常入库 / **抓不到标题也保留条目**（标题退化为 URL，断网契约）/ 重复投喂幂等 / `add-file` 批量导入 / `list` 空态与展示。
- M5 单测：`test_cross_period.py`（50 例：9 结构 / 轨迹 / 坏日与源集合变更归因 / `homogeneous_segments` 同构切分；改结构口径必须补例）、`test_trend.py`（证据包裁剪 / 分段字数与套话校验 / 单段失败只跳该段）、`test_selfcheck.py`（L1–L4 各层 pass/fail、状态文件用 `tmp_path`）。三者都是**纯离线**，用 `tmp_path` 造日报目录，不读仓库里的 `data/reports`
- 覆盖率基线（M6c 实测）：`web/app` 95% / `web/data` 92% / `web/charts` 100% / `render/verdicts`·`render/predictions` 100% / `render/markdown` 93% / `pipeline/daily` 92% / `reasoning/brief` 88% / `cli/commands/inbox` 98% / `cli/commands/knowledge` 93% / `knowledge/export` 99% / `knowledge/daily_index` 92% / `knowledge/store` 94% / `collectors/` 88% / **TOTAL 90%**。

---

## 文档地图（改动前先读）

| 文件 | 用途 |
|---|---|
| `README.md` | 定位 / 能力清单 / 三档模式 / 5 分钟快速开始 / ★ 预言记分板 / mermaid 架构图 / 数据源与合规 / Roadmap（M4 后已重写）。**记分板区块是生成物（"请勿手改数字"）** |
| `CONTRIBUTING.md` | 贡献流程 + 10 条硬规矩（可证伪口径、只读看板、SSOT 只读…）|
| `.github/ISSUE_TEMPLATE/` | bug / feature 表单（bug 表单要求先跑 `doctor`；feature 表单列明 V1 边界）|
| `docs/AI_Pulse_Agent开发执行手册.md` | **SSOT 级执行手册**（v1.22）：全局约定、**红线 44–47（M6c 新增）**、M0–M6 任务卡与 DoD、常见坑、Agent 工作方式要求。开工前必读，**只读** |
| `docs/AI_Pulse_设计方案.md` | 设计 SSOT（v1.22，2697 行），代码注释里的 `§5.x` / `§6.2` / `§7` 都指向它；**只读**。M6c 设计见 §11.6（知识库），M6b 增强见 §11.1 |
| `docs/文档维护日志.md` | 每行 = 一次文档维护对应的 tag/commit；**「维护记录」表倒序排列，新会话先读该表顶部第一行确认基线**（别读格式示例）；Agent 只读 |
| `docs/简报格式规范.md` | 已实现的简报格式规范（头条来源块 / 总览分条 / 四节点评 / 表格列固定与空值占位；M6b 起含「要点 / 为什么重要 / 立场」三列全覆盖约定）|
| `docs/踩坑实录.md` | 按阶段积累的踩坑记录（README 与 CHANGELOG 都链接它）；`CODEBUDDY.md` 末尾的「已归档的坑」是它的浓缩版 |
| `docs/数据源手册.md` | 每个源的端点、真实字段、限速、失效降级路径、探测结论 |
| `docs/新增数据源指南.md` | 加源的标准流程（L1 改配置 / L2 写模块）+ 自检清单 + 常见坑 |
| `docs/开发日志.md` | 每阶段"做了什么 / 踩了什么坑 / 为什么这么决策"，**每阶段结束必须追加**；已有 M0/M1/M2/M3a/M3b/M4/M6a（含 predict 截断补丁）/M6b/**M6c** 九章 |
| `docs/images/dashboard.png` | 看板截图（README「看板预览」引用，取自 2026-10-17 真实日报）|
| `scripts/probe_sources.py` · `scripts/cron_daily.sh` | 数据源探测（加源/改 URL 前必跑）与 WSL 本地 daily cron 备份入口（crontab：`35 7 * * * /home/<you>/projects/aipulse/scripts/cron_daily.sh`，北京 07:35，避开 Actions 的 08:00）|
| `scripts/cron_knowledge.sh` | M6c 知识库导出 cron（方案 E）：不跑本地 daily，只 `git pull --ff-only` + `knowledge export`；工作区检查只看已跟踪改动；日志 `data/logs/cron_knowledge.log` |
| `prompts/{brief,predict,debate,trend}/` | Jinja2 模板落点。`brief/` 有 `daily_brief.j2` + `item_comment.j2`（v2，顶层键 `one_liners`，只产中文要点）+ `item_enhance.j2`（顶层键 `comments`，产 why/stance）；`predict/` 有 `generate.j2` + `verify.j2`；`trend/weekly.j2` 已落地（M5，7 节分段，front-matter 走 strong）；`debate/` 待 M5 下半 |

`configs/scoring.yaml` 的打分权重与 `cluster` 段已被 M2 实际读取（engagement / freshness / velocity / source_weight / cold_start / title_only_weight / cluster），调权重改配置即可，不要改代码。

> `docs/简报格式规范.md` 已随 M6a 落地并入库，可作为**已实现行为**的依据（不再是待实现设计稿）。
> REA 二次诊断的结论是**真掉榜、不是 bug**——`state` 语义正确排除了窗口外条目，不要为"让掉榜项目出现"去改 `time_semantics`；产品解法是已实现的「增速榜」（`analysis/signals.py::velocity_board()`，设计见 `docs/AI_Pulse_设计方案.md` §5.14）。

---

## 已归档的坑（不要重新踩）

| 坑 | 结论 |
|---|---|
| arXiv 严格按 24h 过滤会永远采空 | 索引滞后 3-4 天 → 配置 `lookback_days: 7`，放宽窗口时打 warning |
| Reddit RSS 无 `score` | 三重补偿：`score=0` 但保留 comments + 该源权重降至 0.55 + `rank_score=(N-rank)/N` 作热度代理 |
| 坏 gzip 被写进缓存后一直复现 | 排查先 `--no-cache`；`DecodingError` 已加入可重试异常；必要时请求头加 `Accept-Encoding: identity` |
| httpx 0.28 的 `Response.ext` | 不存在，用 `extensions` 字典；`httpx.Timeout` 必须显式给 `default` |
| SQLModel 字段 `date` 与 `datetime.date` 冲突 | `from datetime import date as date_type` |
| alembic 迁移漏 `import sqlmodel` | 已补进 `script.py.mako`；migrations 目录整体排除 mypy 与 ruff |
| HTML 正则 `r"<p[^>]*>"` | 会误匹配 SVG 的 `<path ...>`，写成 `r"<p(?:\s[^>]*)?>"` |
| 依赖易变 CSS class 解析 HTML | 只用稳定结构（`<article>`、`h2>a[href]`、`itemprop`、文本模式）+ 准备降级通道 |
| 抓不到就丢条目 | 手动投喂降级保留（标题退化为 URL），见 `collectors/inbox.py`；CLI `aipulse inbox add` 同样保证（有回归测试） |
| 库缺 `skip_cluster` 列导致 collect 崩 | pipeline 入口加 `ensure_schema()` 自动 upgrade |
| 装 `types-feedparser` | 注册表无此包，已从 pyproject 移除，不要加回来 |
| `expire_on_commit` 是 **Session** 参数 | `create_engine(expire_on_commit=...)` 直接报错；要在 session 关闭后继续读 item 属性，写 `Session(engine, expire_on_commit=False)`，否则渲染时 `DetachedInstanceError` |
| 实体匹配器全局缓存被 `AIPULSE_ROOT` 污染 | monkeypatch root 后缓存的正则来自空 entities.yaml → 以 `project_root()` 为缓存键，root 变化即 `reset_matcher()` |
| ~~openai 3.x 自带 httpx2 传输~~ | **已作废**：v1.7 移除 `openai` SDK 改 httpx 直连，`respx` 现可拦截 LLM 链路（`tests/unit/test_openai_compat.py`）。不要再按旧结论用桩客户端绕测 |
| Typer `invoke_without_command=True` 回调 + 子命令路由冲突 | 回调在带子命令时也会触发（实测 `predict list` 会先跑自动生成）→ 回调首参加 `ctx: typer.Context`，`ctx.invoked_subcommand is not None` 时直接 return（"默认动作 + 子命令"标准写法） |
| LLM 缓存键未区分 response_format | json_schema 与 json_object 两种响应用同一缓存键会互相污染 → 缓存键的 `response_model_name` 追加 `:js`/`:jo` 后缀 |
| ruff B008 误报 Typer 可重复选项 | `param: list[str] = typer.Option(None, ...)` 被 B008 拦（list 类型默认值）→ 加 `# noqa: B008`（Typer 可重复选项标准写法） |
| 同一作用域复用 `zip` 循环变量名 | 元素类型不同会让 mypy strict 报冲突 → 改名 |
| SQLModel `date` 字段（M2 再现） | `schema/brief.py` 同样用 `from datetime import date as date_type` |
| **Jinja 的 `foo.bar` 先取属性再取键** | `meta.analysis.items` 取到的是 `dict.items` **方法本身**，页面上直接印出 `<built-in method items of dict object at 0x...>` → 模板里取 dict 一律用下标 `meta.analysis['items']`；已加回归断言 `assert "built-in method" not in html` |
| mypy strict 下可空 datetime 列的列方法/比较 | `Prediction.verified_at` 是 `datetime \| None` → `.is_not()` / `.asc()` 报 `union-attr`、`>=` 报 `operator`，`# type: ignore[union-attr]` 还会因错误码不匹配被判"未使用的 ignore" → 用 `cast(Any, Prediction.verified_at)` 收口（沿用"不要凭印象写错误码"）|
| 本地验证 `aipulse serve` | 普通 `&` 起的后台进程会在命令结束后被回收，curl 表现成 `status=000`（不是页面 bug）→ 用 `nohup ... &`，或起在同一命令里再 curl |
| `AIPULSE_ROOT` 指向临时目录 | 找不到 `alembic.ini` → `ensure_schema()` 回落 `create_all`。做隔离演示库时要**先跑一次 `daily`/`ensure_schema` 建表再插数据**，否则 `no such table` |
| **测试里改 `AIPULSE_ROOT` 会连带打断 prompts/configs** | `prompts_dir()` 与 `load_scoring` / `load_entities` 都按 `project_root()` 解析，root 一改就读不到 `prompts/**.j2` → `FileNotFoundError`。**要跑「会调 LLM」的用例，别改 root**，改成注入 `Settings(app={"data_dir": str(tmp_path / "data")}, ...)` 并 monkeypatch `daily.load_settings`（见 `test_run_daily_hybrid_generates_and_stores_predictions`）|
| **`daily` 曾经完全不生成预言（M4 补齐）** | `mode: hybrid` 的定义是预言生成 + 主编点评，但 M2/M3a 只把 `brief` 接进了 daily → **配了 key 记分板样本也不会增长**。已补 `_generate_daily_predictions()` 与 `predictions.md`。改档位相关逻辑前先确认这条路径还在 |
| **干净目录下建库失败（Actions 首跑实测）** | 早期 `data/` 不在仓库里（只被 .gitignore 覆盖）→ `migrate_to_head()` 把 `sqlite:///<abs>` 交给 alembic 时父目录缺失，报 `unable to open database file`。已修：该函数里先 `target.parent.mkdir(parents=True, exist_ok=True)`（`engine_for()` 早有这行）。**`data/reports/**` 现在已入库，验证建库时不要直接删 `data/`（会丢掉历史日报）——改用临时 `AIPULSE_ROOT`，或只移走 `data/*.db`** |
