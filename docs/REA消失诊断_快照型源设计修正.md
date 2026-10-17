# REA 消失之谜 · 诊断与「快照型源」设计修正

> 用户观察：**REA（morluto/rea）15 号报告里有，16/17 号没了**。
> 而我此前说过"持久化不影响条目每天是否出现在日报里"。
> **这里我错了——至少对 GitHub Trending 这类源是错的。** 下面是完整分析。

---

## 一、先排除：不是持久化导致的

持久化（M6a 待做）针对的是 **LLM 产物（那句话）**，与条目是否出现无关。
**而且 M6a 还没开工**，`enhance_top_n` 尚未实现——所以也不是"限额"导致的。

（顺带澄清用户的一个猜测：**"开源项目条目太少是因为限额功能吗" → 不是**，限额功能还没做。）

---

## 二、真正的原因：Trending 是「状态型」源，却被当成「事件型」处理

### 两类数据源的根本区别

| 类型 | 源 | 时间语义 | 例子 |
|---|---|---|---|
| **事件型** | arXiv / HF / HN / RSS | **published_at** = 事件发生时刻，固定不变 | 一篇论文 10-15 发表，就永远是 10-15 |
| **状态型** | **GitHub Trending** | **没有发布时间**，只有"此刻是否在榜" | REA 此刻在榜 = 它是当下热点 |

**Trending 页面给的是一份"当前快照"，不含任何时间戳。**

### Bug 的产生

采集时为 trending 条目赋一个时间（通常是**首次采集时刻**），之后跨天重复采集时
通过 `content_hash` upsert 合并——**合并会保留首次发现时间，不更新**。

于是：

```
10-15  REA 首次被采集 → published_at = 10-15 → 进入 15 号窗口 ✅ 出现在日报
10-16  REA 仍在榜，再次采集 → upsert 合并，published_at 仍是 10-15
       16 号窗口 = 10-15 10:52 → 10-16 10:52 … 边界擦过或已滑出 ❌ 消失
10-17  同理 ❌ 消失
```

**结果：一个持续霸榜的项目，只会出现一天，之后永久消失——即使它每天都被采集到。**

这正好解释 REA 的现象，也解释了为什么 17 号"开源项目只有 3 条"。

### 佐证：17 号 meta.json 的异常

```
collect: ok_sources 6, failed_sources 1, total_items 67   ← 16 号是 7 源 / 164 条
analysis: items 165
```

采集量掉了约 60%，且有 1 个源失败。
**两个问题叠加**：① 快照型源被窗口过滤掉；② 某源采集异常。

从 brief.md 看，"产业与新闻"板块全是 `hackernews`、**没有一条 rss 条目** → 失败的很可能是 RSS 源。

---

## 三、修复方案（★ 建议采纳）

### 核心改动：item 区分两个时间，按源类型选择过滤依据

| 字段 | 含义 |
|---|---|
| `first_seen_at` | 首次发现（用于"新出现"判断、去重） |
| `last_seen_at` | **最近一次被采集到**（每次 upsert 都更新） |
| `published_at` | 事件型源的发布时间（可能为空） |

**窗口过滤规则**：

| 源类型 | 过滤依据 |
|---|---|
| 事件型（arxiv / hf / hn / rss） | `published_at` 落在窗口内 |
| **状态型（github_trending）** | **`last_seen_at` 落在窗口内** —— 只要本次采集还在榜，就该出现 |

### 附带收益

1. **持续热门的项目会持续出现**（符合直觉：霸榜三天就该出现三天）
2. 可以新增一个高价值信号：**「连续在榜 N 天」**——比单日热度更能说明真火
3. `signals` 的 star 快照本来就在追踪项目，现在 item 层面也一致了

### 实现要点

- `store/models.py`：Item 增加 `last_seen_at` 字段 + 迁移
- `store/repo_items.py`：upsert 时**无条件更新** `last_seen_at`
- `analysis` 的窗口过滤：按 `source_type`（新增配置项 `sources.*.time_semantics: event|state`）选择字段
- `configs/sources.yaml`：`github_trending.time_semantics: state`，其余 `event`
- 补单测：**同一 trending 项目连续三天被采集，三天日报都应包含它**（这是核心回归测试）

---

## 四、给 Agent 的查证命令（先确认再改）

在改代码前，请先跑这几条确认根因：

```bash
# 1. REA 在库里的记录与时间戳
sqlite3 data/aipulse.db "SELECT id, substr(title,1,40), source, published_at, first_seen_at, last_seen_at FROM items WHERE title LIKE '%rea%' OR title LIKE '%REA%';"

# 2. 17 号各源采集条数（对比 15/16 号）
sqlite3 data/aipulse.db "SELECT source, count(*) FROM items GROUP BY source ORDER BY 2 DESC;"

# 3. 17 号哪个源失败了
# 看 data/reports/2026/10/17/meta.json 或运行日志里的 source_runs

# 4. 确认 upsert 是否更新了时间字段
```

**如果 REA 的 `published_at` 停在 10-15 而 16/17 号它仍在库里 → 根因确认。**

---

## 五、为什么这个问题值得单独修

它直接影响**你每天打开日报的第一观感**：

> 一个你昨天看到、觉得很火、想今天继续跟进的项目，第二天消失了。

这会让整个日报的可信度打折——**你会开始怀疑"是不是系统漏了"，而不是"它掉榜了"**。
而这种怀疑一旦产生，工具的价值就大打折扣。

**优先级建议：高于 M6a 的内容增强。**
先把"该出现的一定出现"修对，再谈"怎么让它更好读"。
