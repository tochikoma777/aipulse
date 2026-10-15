# M3b 设计 · 预言到期验证与统计（verify 设计）

> **状态**：设计稿（M3b 开工前评审用）。本文件**只做设计**，不含实现代码。
> **SSOT**：`docs/AI Pulse 设计方案 v1`（§7.5 / §10.2.2 / §10.2.3 / §11.4.4 / §11.5 / §16.1 / §18.4）与 `docs/AI Pulse · Agent 开发执行手册 v1`（§0.3 红线 / §4 M3 任务卡 / §7 坑清单 / §8.5 Prompt 管理）。
> **约定**：SSOT 两份文档由项目负责人维护、Agent 只读（设计 §19.4 / 手册红线 15）。本文件不得反向修改 SSOT。

---

## 0. 范围与非目标

| | 内容 |
|---|---|
| ✅ 覆盖 | 到期验证流程、证据检索、量化判据自动判定、人工 `review` 口径、统计与记分板**口径** |
| ❌ 不覆盖 | 生成逻辑（M3a 已完成）、Web 看板（M4）、embedding（M5，默认关闭） |
| 📦 本次交付 | `prompts/predict/verify.j2`（可直接落盘的成品）+ 本设计文档 |
| 🚫 明确不做 | **不创建/修改** `reasoning/verifier.py`、stats 相关代码、任何测试文件 |

---

## 1. 判定口径（★ 本阶段唯一真正需要强模型的地方）

### 1.1 四类判定与分数

| verdict | `verdict_score` | 定义 | 典型触发 |
|---|---|---|---|
| `hit` | **1.0** | 判定标准中**全部可观测条件**均被证据满足（阈值达到 / 事件确已发生 / 可核实事实出现） | 官方发布了权重；repo star 达阈值；论文数超阈值 |
| `partial` | **0.5** | 判定标准由**多个并列条件**构成，部分满足部分未满足；或量化阈值落在题面容差带边缘 | "开源 **且** 登顶 benchmark" 只做到前者；要求 ≥100 实测 95–99 |
| `miss` | **0.0** | 证据对相关话题**已充分覆盖**，但标准明确**未被满足**（未发生 / 未达标 / 被反证） | 到期仍无发布；star 停在阈值下；出现相反事实 |
| `unverifiable` | **NULL** | 无法判定且不可归于 miss | 证据覆盖不足、主题从未出现、依赖不可观测的私有信息 |

> `status` 字段取值 `pending` / `verified` / `unverifiable`；`verdict` 字段取 `hit` / `partial` / `miss`。
> **`unverifiable` 不是 `verdict`，而是 `status`**（详见 §1.4）。

### 1.2 判定优先级（先短路，再上模型）

```
量化判据（criteria 非空）  ──▶  查表/查 signals 直接判定（零 LLM，见 §4）
语义判据（criteria 为空）  ──▶  证据充分度门槛（§3.4）
                                    ├─ 达标 ──▶ LLM 三值判定（§5）
                                    └─ 不达标 ─▶ grace 重试 / unverifiable（§2.3）
```

### 1.3 时间语义

- `due_date = date + horizon_days`，`horizon_days ∈ {7,30,90,180}`。
- **判定窗口**（用于取证据）= `[date, due_date + 3 天]`（解读见 §3.2）。
- **grace（重试窗口）** = 到期后 **+7 天**（§10.2.2）：证据不足时先保持 `pending` 再观察，最多 7 天。
- 时间戳一律 UTC；只在实际证据时间 ≤ `due_date + 3` 时，才允许计入 `hit`。

### 1.4 `unverifiable` 只由系统产生（不由 LLM 产生）

`schema/prediction.py::Verdict` 的 `verdict` 字面量只有 `hit/partial/miss`。本设计**保持该契约不变**，`unverifiable` 完全由 **系统证据门槛**（§3.4）在 grace 耗尽后写入 `status`。

**理由**：若允许 LLM 自行返回 `unverifiable`，它会成为"逃避 miss 的软出口"，直接污染命中率与 Brier 的可信度。把"判不了"交给**可复现的客观门槛**，把"判得准"交给模型——职责分离。

### 1.5 边界规则细则（判定时逐条套用）

1. **量化阈值型**：达标 → `hit`；落入容差带 `[threshold×(1−tolerance), threshold)` → `partial`（`tolerance` 默认 5%，由模板声明）；低于容差带 → `miss`。
2. **多条件（且）**：`statement` / `falsifiable_criteria` 含"且 / 并 / 同时 / 以及" → **全部满足才 `hit`**，部分满足 → `partial`。
3. **多条件（或）**：含"或 / 任一" → **任一满足即 `hit`**（不再给 partial）。
4. **反证即 miss**：出现与断言相反的可观测事实时判 `miss`，即便"目标事件"未现身。
5. **时间边界**：事件发生在 `due_date + 3` 之后 → 不计入 `hit`，判 `miss`（截止已过）。
6. **`partial` 的克制**：仅当**存在明确、可列举的子条件**且部分满足时使用；`verdict_note` 必须逐条列出"满足 / 未满足"。**拿不准 ≠ partial**（拿不准走 §3.4 门槛 → `unverifiable` / 重试）。
7. **`miss` 的前提是"覆盖充分"**：只有当证据确实覆盖了话题（门槛达标）时的"未满足"才算 `miss`；"查不到"不等于"没发生"。

---

## 2. 验证流程设计（verifier，文字化，不给代码）

### 2.1 选取待验证

`status = 'pending' AND due_date <= today`（§10.2.2 步骤 1）。幂等：已 `verified` / `unverifiable` 的不再重复处理，除非显式 `--force` 或人工 `review` 覆盖。

### 2.2 双路径

| 路径 | 触发 | 动作 | 花费 |
|---|---|---|---|
| **量化路径** | `criteria` 非空 | 按 §4 查 `signals` / `entities` / `items` → 直接得 verdict | 零 API |
| **语义路径** | `criteria` 为空 | §3 检索证据 → §3.4 门槛 → §5 调 `verify.j2` | 1 次 LLM |

### 2.3 状态机

```
pending ──(量化判据达标/不达标)──────────────▶ verified (verdict=hit|partial|miss, verified_by=auto)
   │
   ├──(语义: 门槛达标 + LLM 成功)──────────▶ verified (verdict=..., verified_by=auto)
   ├──(语义: 门槛不达标 且 today <= due_date+7)▶ 保持 pending（下轮再试）
   ├──(语义: 门槛不达标 且 today  > due_date+7)▶ unverifiable (verdict=NULL, verified_by=auto)
   └──(LLM 网络/校验失败)───────────────────▶ 保持 pending（下轮再试，绝不写 miss）
```

**硬约束**：单条验证失败（含 LLM 异常、结构化校验失败）**绝不**导致整批/流水线崩溃（手册红线 5、坑 8）；失败只记录日志并保持 `pending`。

### 2.4 人工 review（必须实现，§10.2.2）

```bash
aipulse predict review <prediction_id> --verdict hit  --note "依据：xxx 已于 10-09 发布"
aipulse predict review <prediction_id> --verdict miss --note "截至到期未见发布"
aipulse predict list --status pending      # 待验证队列可视化
```

- 写入 `status='verified'`、`verdict`、`verdict_score`、`verdict_note`、`verdict_evidence_ids`、`verified_at`、`verified_by='human'`。
- **人工可覆盖 auto 结果**（覆盖时在 note 追加"人工复核"字样）；人工判定**同样计入统计**。
- 价值：纯库内检索必有大量"证据不足"，人工一句话即可闭环，避免 `unverifiable` 堆高。

---

## 3. 证据检索策略（语义路径）

### 3.1 关键词来源（字段与权重）

| 来源字段 | 权重 | 说明 |
|---|---|---|
| `statement` | **×3** | 预言主体 |
| `falsifiable_criteria` | **×3** | 判据原文，含最关键的可观测信号 |
| `rationale` | ×1 | 推理依据，补充上下文 |
| 生成时证据（`evidence_item_ids`）的 `title` / `tags` | ×2 | 主题锚点 |
| 生成时证据关联 `topics.name` / `topics.keywords` | ×2 | 主题锚点 |
| `criteria_params` 的 `repo` / `keyword` / `entity` / `owner` | **硬过滤 + 加权词** | 精确字面量，直接检索 |
| `configs/entities.yaml` 命中实体（`analysis/entities.py::matcher()`） | ×2 | 高信号专名 |

**分词**：复用 `analysis/cluster.py::tokenize()`（中文 jieba、英文按词，避免中文整句当单 token —— 手册坑 6）；去停用词与 `len < 2` 的碎片。
**构造查询文档 Q**：按上表权重把字段文本拼接（权重实现为重复拼接 / TF-IDF 词频加权）。

### 3.2 候选窗口

- **窗口** = `[date 00:00 UTC, due_date + 3 天 23:59:59 UTC]`（含宽限）。
- 过滤字段：`item.published_at`（**事件时间**，语义正确）；缺失时回退 `collected_at`。
- ⚠️ 现有 `store/repo_items.py::list_items_collected` 按 `collected_at` 过滤，语义上不等于"事件发生在窗口内"。M3b 建议**新增按 `published_at` 窗口的查询**（设计提示，不在此实现）。

**与 SSOT 的差异（§10.2.2 写的是 `due_date ± 3 天`）**：本设计把左界扩展到生成日 `date`，右界保留 `+3` 天宽限。理由：「截至到期日，若 …… 则命中」这类预言的**命中事件可发生在窗口内任意时点**，若只在 `due_date ± 3` 内检索，会**漏掉早期即已兑现**的预言（把 hit 误判为 miss）。→ **待负责人确认**（见 §8）。

### 3.3 相似度、排序与截断

- **向量化**：复用 `TfidfVectorizer`（`analysis/cluster.py` 同款）；`fit` 于 `[Q] + 候选集`，算 `cosine(Q, 每条候选)`。
- **阈值**：
  - `similarity_threshold = 0.15` —— 进入候选池的下限（短查询 vs 长文本的余弦普遍低于 item-to-item 的 0.35，故低于聚类阈值）。
  - `strong_similarity = 0.30` —— 单条即可视为"强证据"（供 §3.4 门槛使用）。
- **排序打分**：`relevance = 0.7 × cosine + 0.3 × min(hot_score / 100, 1)`；同分按 `published_at` 降序。
- **Truncation（Top 20）**：
  1. 按 `relevance` 降序取前 `evidence_top_k = 20`；
  2. 每条 `summary` 用 `utils/text.truncate_summary(≤300)`；
  3. 复用 `reasoning/predictor.py` 的 token 预算裁剪思路（总量超 `12000` token 时**从尾部丢弃**，即丢掉最不相关的）。
- **硬过滤**：`criteria_params` 指定来源时限制 `source`（`hn_story_points`→`hackernews`、`arxiv_paper_count`→`arxiv`、`github_*`→`github`/`huggingface`）。
- **生成时证据**：`evidence_item_ids` 若仍在库中，作为**独立区块**注入（标注"生成时证据"），便于模型对照，但**不计入**充分度门槛（它们是生成时的依据，不是到期证据）。

### 3.4 证据充分度门槛（决定是否调用 LLM）

**充分** ⇔
`(cosine ≥ similarity_threshold 的候选数 ≥ min_evidence=3)`
**或** `(max cosine ≥ strong_similarity=0.30)`。

- 充分 → 调 LLM（§5）。
- 不充分 → 按 §2.3 走 grace：`today ≤ due_date+7` 保持 `pending`；否则置 `unverifiable`。
- **门槛的判定完全客观、可复现**，不含模型主观判断。

---

## 4. 量化判据自动判定（`configs/criteria.yaml`，零 LLM，§11.5）

| 模板 | 参数 | 判定数据源与口径 |
|---|---|---|
| `github_new_repo` | `owner` | `signals` 中 `entity_type='repo'` 且 `entity_key` 前缀 `owner/` 的集合，窗口内是否**出现新 key** |
| `github_stars_reach` | `repo`, `threshold` | `signals(entity_key=repo, metric='stars')` 在窗口内（重点 `due_date` 附近）**最大值 ≥ threshold** |
| `hn_story_points` | `keyword`, `threshold` | `items(source='hackernews')` 且标题/摘要含 `keyword`，`metrics['score']` **最大值 ≥ threshold** |
| `entity_mentions` | `entity`, `threshold`, `window_days` | `entities` 表窗口内该 `name` 计数 **≥ threshold** |
| `arxiv_paper_count` | `keyword`, `threshold`, `window_days` | `items(source='arxiv')` 窗口内含 `keyword` 的条目数 **≥ threshold** |
| `custom` | `expr` | ⚠️ 兜底：M3b 仅支持受限布尔表达式（`>= <= == and or` + 计数函数）→ **表达式求值范围未定，标 TODO**，解析失败则落回语义路径 |

**判分**：达标 → `hit(1.0)`；阈值型落入容差带（默认 5%）→ `partial(0.5)`；不达标 → `miss(0.0)`。
**证据**：`verdict_evidence_ids` 记录实际命中的 `item_id`（如那篇 HN 故事 / 那个 repo 的信号来源）。
**收益**（§11.5）：省钱（不走 LLM）、快（查表即判）、倒逼预言写清楚；**off 档也能完成"生成→到期→验证→记分板"全闭环**（M3 DoD）。

---

## 5. LLM 结构化契约与降级

- **契约**：`schema/prediction.py::Verdict`（`verdict: Literal['hit','partial','miss']` + `verdict_note` + `verdict_evidence_ids`）。**不新增 `unverifiable`**（理由见 §1.4）。
- **调用**：`llm/structured.py::generate_structured(client, messages, response_model=Verdict, temperature=0.2, purpose='predict_verify', model_tier='strong')`；模板元信息取自 `llm/prompt.py::render_prompt('predict/verify', ...)`。
- **降级**：网络异常 / 结构化校验两轮仍失败 → 保持 `pending`（下轮重试），**不写 verdict**，**绝不**把失败当 `miss`。
- **缓存**：沿用 `llm_cache`；`json_schema` / `json_object` 的缓存键后缀 `:js` / `:jo` 已由 M3a 处理（§18.4 坑 4），勿重复实现。

---

## 6. 统计与展示口径（供 `stats --predictions` 后续实现）

1. **分母规则**：`unverifiable` 与 `pending` **不计入**命中率 / Brier；单独展示计数。
2. **N** = `status='verified'` 的条数。
   - **严格命中率** = `hits / N`
   - **加权分** = `mean(verdict_score)`
3. **Brier Score** = `mean((confidence − verdict_score)²)`，越低越好（<0.20 优秀，≈0.25 为随机猜测基线附近）。⚠️ `partial` 的 outcome 取 0.5（非二值）——口径**待确认**（§8）。
4. **校准曲线分桶**：各桶展示 `样本数 / 声称置信度均值 / 实际命中率`。
   ⚠️ SSOT §10.2.3 只列了 `0.5-0.6 / 0.6-0.7 / 0.7-0.8 / 0.8+` 四桶，但 `confidence` 可低至 **0.05**。**建议补一个低置信桶 `[0.05, 0.5)`**，否则低置信预言无法进入校准。
5. **分组统计**：`category` / `horizon_days` / `model` / `prompt_version` / `origin(human|llm)` 各自的 N、命中率、加权分。
6. **样本量提示**：`N < 10` 时标注"样本不足，仅供参考"（呼应 §19.5 宁缺毋滥）。
7. **空态**：`N = 0` 时输出"系统已运行 X 天，首批预言将于 Y 日到期"（手册坑 18），不报错。
8. **记分板 Markdown**：由 render 层生成，含"总览 + 校准表 + 分组"三段，格式可直接贴 README（§10.2.3 / DoD）。

---

## 7. 建议新增配置（`configs/default.yaml` → `verify` 段）

```yaml
verify:
  grace_days: 7                 # 证据不足时的重试窗口（§10.2.2）
  evidence_window_grace_days: 3 # 判定窗口右界宽限（§3.2）
  evidence_top_k: 20            # 证据截断条数（§10.2.2 / §3.3）
  similarity_threshold: 0.15    # 进候选池的余弦下限（§3.3）
  strong_similarity: 0.30       # 单项强证据阈值（§3.4）
  min_evidence: 3               # 语义路径的证据充分度下限（§3.4）
```

（`pipeline.auto_verify` 已存在，作为"每日流水线是否自动跑 verify"的开关。）

---

## 8. 与 SSOT 的差异 / 待负责人确认

| # | 事项 | 本设计 | SSOT 原文 | 建议 |
|---|---|---|---|---|
| 1 | 证据检索窗口 | `[date, due_date+3]` | §10.2.2：`due_date ± 3 天` | 左界扩至生成日，避免漏判早期兑现的 hit（§3.2） |
| 2 | Brier 的 outcome | `partial=0.5` | §10.2.3 未明确 partial 处理 | 确认是否按 0.5 计入，或 partial 不计入 |
| 3 | 校准分桶 | 增补 `[0.05,0.5)` 低置信桶 | §10.2.3 四桶自 0.5 起 | 增桶，否则低置信预言无法校准 |
| 4 | `custom` 判据表达式 | 受限布尔表达式，TODO | §11.5：兜底供高级用户 | 确认求值沙箱范围 |

---

## 9. 红线自检（对齐手册 §0.3）

- 预言必须可证伪（M3a 已保证）；`falsifiable_criteria` 留空不得入库（红线 18）。
- 手写预言已收集 `category`（红线 19），M3b 的分组统计才有效。
- 验证"给证据说话"：`verdict_note` 必须引用 item id 或说明"证据不足"（M3 任务卡约束）。
- off 档零网络：量化判据可独立闭环（M3 DoD ★）。
- 单条失败不崩流水线（红线 5）；`--json` 时日志走 stderr。
- **不改 SSOT**（红线 15）；不实现微信 / X（红线 6）。

---

## 附录 A · `prompts/predict/verify.j2`（成品，与仓库文件一致）

> 已由 `llm/prompt.py` 成功加载：front-matter `version=1 / model_tier=strong / temperature=0.2 / purpose=predict_verify`，`version_hash=ae882480`。

````jinja
---
version: 1
model_tier: strong
temperature: 0.2
purpose: predict_verify
---

你是 AI Pulse 的「预言核对员」。你只做一件事：**依据给定证据，判断一条到期预言是否命中**。你不预测未来，也不改写预言，只核对。

# 待核对预言
- 生成日期：{{ generated_date }}
- 到期日期：{{ due_date }}（horizon_days = {{ horizon_days }}）
- 判定窗口：{{ window_start }} ~ {{ window_end }}
- 类别（category）：{{ category }}
- 置信度（confidence）：{{ confidence }}
- 预言（statement）：{{ statement }}
- 判定标准（falsifiable_criteria）：{{ falsifiable_criteria }}
- 推理依据（rationale）：{{ rationale }}
{% if criteria %}
- 量化判据模板：`{{ criteria }}`，参数 {{ criteria_params }}
{% endif %}

# 到期窗口内检索到的证据（共 {{ evidence_count }} 条，按相关度降序）
```json
{{ evidence_json }}
```

# 判定规则（严格执行，不得自创）
1. `hit`（得分 1.0）：判定标准中的**全部可观测条件**均已在证据中被满足——阈值达到、事件确已发生、或可核实的事实（发布 / 上榜 / 仓库 / 论文）明确出现。必须由证据**直接**支持，不允许"看起来像"。
2. `partial`（得分 0.5）：判定标准由**多个并列条件**构成，其中一部分满足、一部分未满足；或量化阈值恰好落在题面给出的容差带边缘（例如标准要求 ≥100，实测 95–99）。**禁止**把"单纯拿不准"当作 partial。
3. `miss`（得分 0.0）：证据对相关话题已有**充分覆盖**，但判定标准明确**未被满足**——事件未发生、阈值未达到、或结论被证据反证。

> 系统**只在证据覆盖度达标时**才会调用你。因此在此前提下，**不满足即 `miss`**——不要用"证据不足"回避判定；证据不足的情形已在调用你之前被系统拦截。

# 硬性要求
1. `verdict` 只能取 `hit` / `partial` / `miss` 三者之一。
2. `verdict_note` 必须**引用具体证据 id**（如 `it_ab12…`）说明判定理由；`hit` / `partial` 至少引用 1 条；`miss` 若证据为空，须说明"检索到的均为无关条目"。
3. `verdict_evidence_ids` 列出你**实际依据**的条目 id（可为空数组）。
4. 判定以 `falsifiable_criteria` 原文为准，不得擅自放宽或收紧；"即将发布""有望"这类模糊迹象**不能**替代事实。
5. 只输出一个 JSON 对象，不要任何解释文字或代码围栏：
   `{"verdict": "hit", "verdict_note": "……", "verdict_evidence_ids": ["it_xxx"]}`

# 判定纪律
- 宁可判 `miss` 也不要为"给面子"判 `partial`；宁可判 `partial` 也不要无据判 `hit`。
- 与预言无关的证据不要引用；证据里没有的内容不要编造 id。
````

## 附录 B · `verify.j2` 变量契约

| 变量 | 类型 | 来源 |
|---|---|---|
| `generated_date` | str `YYYY-MM-DD` | `prediction.date` |
| `due_date` | str `YYYY-MM-DD` | `prediction.due_date` |
| `horizon_days` | int | `prediction.horizon_days` |
| `window_start` / `window_end` | str `YYYY-MM-DD` | §3.2 计算 |
| `category` | str | `prediction.category` |
| `confidence` | float | `prediction.confidence` |
| `statement` | str | `prediction.statement` |
| `falsifiable_criteria` | str | `prediction.falsifiable_criteria` |
| `rationale` | str | `prediction.rationale` |
| `criteria` | str \| None | `prediction.criteria`（语义路径传 `None`） |
| `criteria_params` | dict \| None | `prediction.criteria_params` |
| `evidence_count` | int | 检索到的证据条数 |
| `evidence_json` | str | 证据列表 JSON（`id/title/source/published_at/summary/relevance`） |

> `render_prompt` 使用 `StrictUndefined`：缺任一变量会立即报错，不会静默渲染为空。语义路径调用时 `criteria` / `criteria_params` 必须显式传 `None`。
