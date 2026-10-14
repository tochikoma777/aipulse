# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## 项目身份

`aipulse`（AI 脉搏）：每日采集 AI 领域热点，产出可回测的推演与预言。Python 3.11 + `uv`，SQLite 单文件存储，MIT。

**里程碑状态（改动前先确认当前阶段）**：M0（骨架 + 数据源探测）与 M1（6 采集器 + inbox + 三级去重）已完成；**当前下一阶段是 M2**（热度打分 / 聚类 / 每日简报）。M3 预言系统 → M4 Actions 自动化 + Web 看板 + README 发布 → M5 周期长文 + 多角色辩论。不要跨阶段实现。

`src/aipulse/cli/commands/` 下除 `init` / `doctor` / `collect` 外，其余（`normalize`/`analyze`/`brief`/`predict`/`debate`/`trend`/`daily`/`stats`/`topics`/`search`/`inbox`/`sources`/`serve`）都是 `placeholder_app()` 生成的占位 Typer 子应用，调用时抛 `NotImplementedError`。它们出现在 `--help` 里是刻意的，不是漏实现。

---

## 常用命令

环境：必须在 WSL2 原生 ext4 文件系统内（**不要放 `/mnt/c/`**：I/O 极慢、SQLite 锁异常、git 行为诡异）。

```bash
uv sync                                   # 安装依赖（含 dev 组）
uv run aipulse --help                     # 命令树
uv run aipulse init                       # 建库（alembic upgrade head）+ 目录骨架 + .env
uv run aipulse doctor                     # 环境体检：Python/LLM key/代理/磁盘/DB/各源连通性
uv run aipulse collect --since 24h        # 采集（单源失败隔离，退出码恒为 0）
uv run aipulse collect --sources arxiv,hackernews --dry-run --json
uv run aipulse doctor --no-network --json # 离线体检
```

### 测试 / 质量门禁（全部对应 CI：`.github/workflows/ci.yml`）

```bash
uv run pytest                             # 全量（约 142 条，无需网络、无需密钥）
uv run pytest tests/unit/test_dedup.py                      # 单文件
uv run pytest "tests/unit/test_dedup.py::test_l2_merges_arxiv_and_hf_same_paper" -q  # 单用例
uv run pytest -q --cov=aipulse --cov-report=term            # 覆盖率（collectors/ 基线 ≥80%）

uv run ruff check .                       # lint（line-length=100，select=E,F,I,UP,B,SIM）
uv run ruff format --check .              # 格式检查
uv run mypy src/aipulse                   # strict；migrations 目录已排除

uv run pre-commit install                 # 钩子：ruff --fix + ruff-format + mypy + pytest
```

`mypy` 为全局 `strict = true`，但对 `aipulse.cli.*` / `aipulse.collectors.*` / `aipulse.pipeline.*` / `aipulse.web.*` 关闭了 `disallow_untyped_defs` 与 `disallow_untyped_calls`。`core/` `schema/` `analysis/` 必须完整通过 strict。

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

---

## 架构：一条数据穿过七层

```
configs/*.yaml ──> collectors/ ──> RawItem ──> normalize/dedup ──> store/repo_items ──> SQLite
      │                  │                          │                     │
   core/config      utils/http              pipeline/collect        store/models
  （YAML+${ENV}）  （限速/重试/缓存）        （编排 + 故障隔离）      （SQLModel 9 表）
```

CLI（`typer`）→ `pipeline/collect.py`（编排）是唯一的横向入口；采集器之间不互相调用，只通过 `RawItem` 与编排层通信。

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
| `store/models.py` | 9 张表：`items` / `signals` / `topics` / `entities` / `predictions` / `source_runs` / `pipeline_runs` / `llm_usage` / `llm_cache`。JSON 字段用 `sa_column=Column(JSON)`，不手写 `json.dumps` |
| `store/repo_items.py` | `upsert_items` / `write_signals` / `clusterable_items` |
| `pipeline/collect.py` | `run_collect()`：`asyncio.gather` + 并发信号量（默认 6），每源独立 `try/except`，写 `source_runs`，落库前去重 |
| `notify/base.py` | `Notifier` Protocol + `FileNotifier`（唯一实现）。其余渠道明确 `NotImplementedError` |

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

---

## 配置与环境

三档运行模式（`configs/default.yaml` 的 `mode`）：`off`（零 API 花费）/ `hybrid`（预言生成 + 主编点评）/ `full`（全部）。`Settings.effective_mode()` 在 `llm.enabled=false` 或 `api_key` 为空时**自动降级为 `off`**，只提示一次，不报错退出。

**数据源环境分级（本地 WSL 与 Actions 网络可达性不同）**：

| `availability` | 本地（未设 `AIPULSE_ENV`） | Actions（`AIPULSE_ENV=actions`） |
|---|---|---|
| `always` | 正常采集，失败计入统计 | 正常采集 |
| `actions_only` | **跳过**，写 `skipped_offline`，不计失败 | 正常采集 |

当前 `hf_papers` / `reddit` 标 `actions_only`。**不要因为本地测不到就把源写死禁用，也不要把本地跳过当 bug 排查。**

环境变量：`.env` 由 `aipulse init` 从 `.env.example` 复制（不含真实密钥）。关键项：`AIPULSE_LLM__BASE_URL` / `AIPULSE_LLM__API_KEY`、`GITHUB_TOKEN`（GitHub Search API 30 req/min，无 token 只有 10）、`HF_TOKEN`、`HTTP(S)_PROXY`、`AIPULSE_ROOT`（测试指向临时目录）、`AIPULSE_ENV`。

`configs/sources.yaml` 的 `rate_limit` 是**必填**项，形状 `"N/period"`，period 支持 `s/m/h/d`（如 `3/s`、`10/1s`、`1/6h`）。

---

## 硬性约定（CI 与人工验收都会查）

### 十四条红线（违反即返工，完整版见 `docs/AI Pulse · Agent 开发执行手册 v1` §0.3）

1. 不一次性生成整个项目——分阶段，DoD 全勾再进下一张卡。
2. **不凭想象写字段解析**——必须基于 `tests/fixtures/` 的真实响应快照。
3. **prompt 不写进 `.py`**——一律 `prompts/**.j2`（目录已建：`brief/` `debate/` `trend/` `predict/`）。
4. LLM 输出不直接 `json.loads`——必须 response_model + 校验 + 一次修复重试 + 再失败降级跳过。
5. 单源异常不得导致整条流水线崩溃。
6. **不实现任何微信 / X（Twitter）相关的采集器、配置段、环境变量或 RSS 桥**——v1.1 已彻底移除，相关内容只能走 `aipulse inbox add <url>` 手动投喂。
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

新增数据源：RSS/Atom 类**改 `configs/sources.yaml` 的 `rss.feeds` 即可，零代码**；新类型源才写 `BaseCollector` 子类 + 在 `registry.py` 注册。扩 `SourceEnum` 需同步改 3 处（枚举、`_DISPLAY_NAMES`、指南文档）——这是刻意的摩擦，先确认现有源 + RSS 覆盖不了。完整流程见 `docs/新增数据源指南.md`。

---

## 测试约定

- `asyncio_mode = "auto"`（无需给每个 async 用例加装饰器），`testpaths = ["tests"]`。
- **全部测试必须无需网络、无需密钥**（CI 无 secrets 且必须全绿）。HTTP 用 `respx` 拦截；`HttpClient` 构造时传 `cache_enabled=False`。
- `tests/conftest.py` 提供 `fixtures_dir` / `fixture_text()` / `fixture_bytes()` / `make_cfg()` / `make_feed()` / `make_http()`。
- 解析器测试是 **fixtures 驱动、先测试后实现**：先落真实响应到 `tests/fixtures/`，把 fixture 变成断言，再写解析代码。每个采集器至少 3 类用例：正常解析 / 边界（空、单条、窗口内无内容）/ 脏数据（缺字段、结构变更 → 不崩、不编造数据）。
- 运行时测试放 `tests/unit/test_collectors_runtime.py`（`respx` mock 抓取流程与降级路径）。
- `tests/integration/test_fixtures.py` 是 **fixtures 契约测试**：快照缺失时 `pytest.skip` 显式标出（**不得静默通过**），并断言每个源探测记录都有明确结论、失败源带错误信息。
- **测试统一用 30 天窗口**写断言——fixture 是冻结快照，用 `--since 24h` 会随时间流逝而失效。
- `collectors/` 覆盖率基线 ≥80%（当前 87%）。

---

## 文档地图（改动前先读）

| 文件 | 用途 |
|---|---|
| `README.md` | 定位 / Roadmap / 快速开始 / 合规声明 |
| `docs/AI Pulse · Agent 开发执行手册 v1` | **SSOT 级执行手册**：全局约定、14 条红线、M0–M5 任务卡与 DoD、32 条常见坑、Agent 工作方式要求。开工前必读 |
| `docs/AI Pulse 设计方案 v1` | 设计 SSOT（1649 行），代码注释里的 `§5.x` / `§6.2` / `§7` 都指向它 |
| `docs/数据源手册.md` | 每个源的端点、真实字段、限速、失效降级路径、探测结论 |
| `docs/新增数据源指南.md` | 加源的标准流程（L1 改配置 / L2 写模块）+ 自检清单 + 常见坑 |
| `docs/开发日志.md` | 每阶段"做了什么 / 踩了什么坑 / 为什么这么决策"，**每阶段结束必须追加** |
| `prompts/{brief,debate,trend,predict}/` | M2+ 的 Jinja2 模板落点（当前为空目录） |

`configs/scoring.yaml` 已落 M2 打分权重骨架（engagement / freshness / velocity / source_weight），M2 实现时读取，改配置不应改代码。

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
| 抓不到就丢条目 | 手动投喂降级保留（标题退化为 URL），见 `collectors/inbox.py` |
| 库缺 `skip_cluster` 列导致 collect 崩 | pipeline 入口加 `ensure_schema()` 自动 upgrade |
| 装 `types-feedparser` | 注册表无此包，已从 pyproject 移除，不要加回来 |
