# AI Pulse 设计方案

> ★ **当前版本：v1.20** · 对应基线 `star-tracking` / `cdcab79` · 详见 `docs/文档维护日志.md`
> 文件名**固定不带版本号**——版本由文档头与维护日志标识，历史由 git 管理。

> 一句话定位：**每日自动采集 AI 领域热点，不只整理，还给出可回测的推演与预言。**


> 本文档是给开发 Agent（CodeBuddy / Claude Code / Cursor 等）执行的**唯一事实来源（SSOT）**。
> Agent 必须严格按本方案实现，任何与文档冲突的"更好想法"必须先向项目负责人提出确认，不得擅自更改架构。

**变更摘要（2026-10-11，已与项目负责人确认）**

v1.1：
1. **移除微信公众号 / X 支持**（含 RSS 桥），改为纯手动投喂通道
2. **主力 LLM 定为 DeepSeek**（`deepseek-chat` / `deepseek-reasoner`），OpenAI 兼容协议
3. **命名定为 `aipulse`（AI 脉搏），许可证改为 MIT**
4. **里程碑重排**：M3 之后先做发布与自动化（原 M5），再做深度推演能力（原 M4）——理由见 §16.0

v1.2（第二轮确认）：
5. **RSS 源策略 = 英文主干 + 中文补充**，中文源失效视为可接受的降级（§5.7）
6. **Reddit 先用免认证 RSS**，M1 验收后再评估是否升级 OAuth（§5.6 / §19.1-6）
7. **M0 即建公开仓库**，README 顶部标注 `WIP / 开发中`（§19.1-14、§14.2）
8. **日报触达 = 文件 + Web 看板为主**，但**架构上必须预留统一 Notifier 抽象**，后续可加邮件/TG/飞书（§11.2）

v1.20（★ 增速榜可比性修正）：
80. **★ 增速榜按「日均增量」排序，不按绝对增量**（§5.14）——
    不同项目快照窗口长度不同，按绝对值排会让「7 天涨 5000」排在「1 天涨 3000」前，
    而后者实际快 7 倍。**增速榜的全部价值就在"谁涨得快"，不可比等于没用**
81. **日均只用于排序，不作为显示值** —— 显示仍给绝对增量但**必须带窗口**（`+8617 / 10h`）。
    理由：显示日均会退化成"每小时速率"的同类问题，短窗口样本被放大成离谱数字；
    **排序是内部比较可归一化，显示要给读者无歧义的原始事实**
82. `insufficient`（窗口 <6h）继续排除出增速榜；表格「增量」列同样带窗口标记
83. 收尾：SSOT 改固定文件名（版本由 git 管理）；docs/ 清理过程性文档

v1.19（★ REA 诊断结案：真掉榜，不是 bug；star 追踪立项）：
75. **★ REA 诊断结案：真掉榜，不是 bug**（§5.14）——
    17 号采集 7 条 trending 无 REA、`failed_sources=0`、REA 最后被采到比窗口起点早 7.6 小时。
    **M6a 的 `state` 修复行为完全正确**
76. **★ 但暴露真实缺口**：REA 有 270369 star、10 小时 +8617，**因掉榜在日报彻底消失**。
    `signals` 表一直记着这些数据却没展示 → **「增速榜」立项**（§5.14）
77. **★ 增量只显示绝对增量，不显示每小时速率**（§5.14）——
    沿用三态规则，`insufficient` 时**给绝对增量但不给速率**（M4 已定：绝不显示被短窗口放大的离谱数字）
78. **日报目录新增 `source_runs.json`**（§14.1）——本地库停在 10-13 无法代表 Actions 状态，
    `source_runs` 未落盘导致"某项目怎么没了"只能靠猜。属**关键状态显式暴露**
79. **诊断列名修正**：`signals` 表正确列名是 `entity_type` / `entity_key` / `metric` / `value` / `ts`

v1.18（★ P0 调整：star 追踪优先于 M6b；文档维护规范固化）：
69. **★ 开源项目板块增加「star 总数 + 增量」列**（§5.14，P0）——
    数据来源 `signals` 表已有，主要是展示层改动
70. **★ 区分「今日 Trending」与「持续追踪」两个概念**（§5.14）——
    快照型源掉榜即消失是天然缺陷，**用 star 序列追踪补上**，
    让"我很关注的项目"不会因为某天没上榜就彻底消失
71. **REA 二次诊断待办**（§5.14）——先分清"仍在上榜但没进日报（bug）"与"已掉榜（正确行为）"，**不要一上来就改代码**
72. **★ 文档维护日志规范**（§19.5）——每次维护记录对应 tag/commit 与一句话总结；
    **必须先提交代码打 tag，再刷新文档**，否则 tag 栏写不出来
73. **优先级调整**：star 追踪（P0）> M6b（P1）> 格式进一步优化（P2）
74. **项目定位修正：不是"开发完就结束"，而是"使用反馈驱动持续迭代"**（§20）

v1.17（★ predict 已恢复；M6b 设计定型）：
63. **★ predict 已恢复**：截断是根因（`first_len=3442` 在 rationale 中途断，`retry_len=0`）。
    修复 = `max_tokens` 分档（fast 4000 / **strong 8000**）+ 候选池 Top 20 只给 id+标题（§10.2.1）
64. **★ M6b：why/stance 从 `daily_brief.j2` 剥离，改由独立批量增强调用产出**（§11.1）
    —— 两处都产出会冲突；且剥离后 brief 输出变短，降低截断风险
65. **★ LLM 输出必须紧凑：只返回 `id + why + stance`，不回显标题/摘要**（§11.1）
    —— 这是从 predict 截断事故里学到的硬约束，不是风格偏好
66. **中文概述单独一次调用**（不与 why/stance 挤同一输出）+ 开关 `brief.zh_summary_enabled`
67. **增强失败不得拖垮日报**：degraded 时日报照常产出，why/stance 为 `—`
68. **Actions `runs-on` 固定 `ubuntu-24.04`**（避开 ubuntu-latest 于 2026-10-19 迁移到 Ubuntu 26）

v1.16（★ 窗口修好后预言生成反降为 0 条：上下文膨胀的连锁反应）：
57. **★ 预言生成的候选证据池收窄为 Top 20 且只给 `id + 标题`**（§10.2.1）
    —— 窗口从 7h 修成 24h 后 items 从 1 涨到 174，池从 1 条变 30-50 条（含摘要），
    **输入膨胀约 10 倍** → reasoner 撞 max_tokens → plain 解析失败 → **生成 0 条**
58. **★ `max_tokens` 必须按 fast/strong 分档并验证真的透传**（§8.2）
    —— 此前"实测无截断"所以没动，但那是因为数据规模还没触发。**配置写了不等于生效**（同 timeout_s 的教训）
59. **degraded 时必须打印原始输出前 500 字符**（§8.3）——用于区分"截断"与"格式错误"，**没有这一步全是猜**
60. **predict 档位保留 strong，但若 plain 结构性不可靠则改 fast**（§10.2.1）
    —— **"生成 0 条"比"质量稍差但有 5 条"糟糕得多**，记分板价值建立在样本量上
61. **★ M6b 的起点比预想的好**：brief v3 已让模型对部分条目产出 why/stance（§18.8）。
    M6b 的目标不是从零设计，而是**让 Top N 全部覆盖且风格统一**
62. **跨板块重复条目需去重**：同一 item 出现在多个板块时应只保留主板块（§11.1）

v1.15（★ 窗口语义第三态 `discovery`，修 arXiv 滞后丢失）：
53. **★ 时间语义三态，不是两态**（§5.13）：`event` / `state` / **`discovery`**
    —— v1.14 只有 event/state 两态，导致 arXiv/HF 按 `published_at` 过滤时
    **因索引滞后 3-4 天而大量丢失**（M1 的 lookback_days:7 采了却进不了日报，等于白采）
54. **arXiv / HF 用 `discovery`（`first_seen_at`）** —— 读者关心的是"今天新发现了什么"，
    不是"这篇论文的投稿日期是不是今天"
55. **简报每板块条数上限**（`brief.max_items_per_section`，默认 10）——
    24 条论文全列违背"帮你果断放弃大部分"的原则
56. **「一句话」列在 off 档显示的是摘要截断** → 列名改为「要点」（兼容模型生成与摘要降级两种态）

v1.14（★ 真实日报审阅后：两个必须修的问题）：
50. **★ 数据源分为「事件型 / 状态型」，窗口过滤依据不同**（§5.13）
    —— GitHub Trending 是**状态型**（无发布时间，只有"此刻是否在榜"），
    此前被当成事件型处理，导致**持续热门项目只出现一天就永久消失**。
    修复：Item 增加 `last_seen_at`；`time_semantics: event|state`；状态型用 `last_seen_at` 过滤
51. **★ 简报格式规范化**（§11.1）——用户反馈"内容还行但格式乱"。
    要点：头条带来源、总览分条、点评拆四节带图标、**条目统一用表格且空值占位**（详略不一的根源）
52. **M6 重排为 M6a（格式+订阅）/ M6b（两项 LLM 增强）/ M6c（知识库）**——**格式优先于内容增强**

v1.13（★ M4 正式收口，进入观察期）：
46. **★ M4 收口**：采集 / 分析 / 简报 / 预言 / 验证 / 记分板 / 自动化 **全部真实跑通**
    （run 38993912848：hybrid / degraded=false / 7 源 164 条 / 5 条预言 / 主编点评非空 / 1m24s）
47. **主编点评质量的实证样本**（§18.7）——它证明了 LLM 环节的真实价值，
    **且为 M6a 的「为什么重要」提供了 prompt 风格范本**
48. **Actions 报告 commit 的正确姿势**：`git fetch` + `git reset --soft FETCH_HEAD`，
    **不是 `pull --rebase`**（同日重跑必然内容冲突导致丢报告）。报告即数据库，丢了不可恢复（§14.1）
49. **`max_tokens` 暂不动**：reasoner 现仅用于预言生成/验证，实测无截断

v1.12（★ 主编点评每日降级 = AI 点评从未真正生效）：
42. **★ 主编点评必须走 `fast` 档（`deepseek-chatt`）**——它属于轻任务（§8.2）。
    此前走 `reasoner` 导致每日 `json_schema_unsupported → json_object → degraded`，
    **配了 key 以来 AI 点评从未生效过**，且更贵更慢
43. **★ 结构化输出降级补第三级 `plain`**：`json_schema` → `json_object` → **无 response_format + prompt 内嵌 schema + 文本解析**。
    `deepseek-reasoner` 两个 structured 参数都不支持，缺这一级就只能 degraded（§8.3）
44. **降级状态按 `(model, format)` 记忆，不是全局布尔**——chat 支持 json_object 而 reasoner 不支持，
    全局记忆会让 chat 被错误降级（§8.3）
45. `max_tokens` 按 fast/strong 分档设置（strong 更大，因 reasoner 有思维链输出）（§8.2）

v1.11（hybrid 真实运行后：★ 两个会毁掉可信度的 bug 必须修）：
38. **★ `evidence_item_ids` 必须做存在性校验 + prompt 注入候选池**（§10.2.1）
    —— 真实运行发现：当天窗口只有 1 条 item，模型却产出 4 条预言共 8 个证据 id，
    **必然存在幻觉 id**。这直接违反红线 1（预言必须基于真实证据），会污染整个记分板
39. **★ 采集与分析窗口统一为「滚动 24h」，cron 改到 UTC 00:00（北京 08:00）**（§14.1 / §18.6）
    —— 原设计 collect 用滚动 24h、analyze 用"本地今天"，两处独立计算导致定时跑时只覆盖约 7 小时；
    **且"本地今天"语义会错过美西当天全部 AI 发布**
40. **配置占位符划线原则**：环境开关用 `${ENV}` 占位符，**算法阈值保留字面量**纳入 git 版本化（§18.6）
41. hybrid 真实运行实证：4 条预言全部带量化判据、timeout 分档（strong 180s）、
    超时降级为"本次未生成"（§18.6）

v1.10（M3b 验收后：★ 预言系统已闭环，四项口径裁定）：
33. **★ M3b 完成，预言系统闭环**：采集→简报→预言→到期验证→记分板全链路打通，
    **off 档零 API 花费可跑通全流程**（实测 `llm_usage` 行数 = 0）
34. **验证模型按档位联动**：`hybrid` 档用 `fast`、`full` 档用 `strong`，配置 `verify.model_tier`（§10.2.2）
35. **`custom` 判据保持 5 原语 + and/or/not，暂不扩展** —— YAGNI，6 个模板已覆盖常见场景（§11.5）
36. **记分板由 daily 流水线自动产出** `data/reports/YYYY/MM/DD/scoreboard.md`；
    `stats` 命令默认只读打印，`--out` 才落盘（§11.1）
37. **M3b 实证坑位归档**：mypy strict 类型别名、`no-any-return` 误写 `type: ignore`（§18.5）

> **重要节点**：M3b 完成后，**记分板的价值开始随时间自动增长**。
> 因此 M4 的第一优先级是 Actions 自动化——**让系统尽快开始每天跑**。

v1.9（M3b 设计评审后裁定，★ 三处统计口径，直接影响记分板可信度）：
29. **证据窗口 = `[生成日, due_date + 3天]`**（左界从生成日起，非 `due_date ± 3 天`）——
    否则"生成后很早就兑现"的预言会因窗口未覆盖而被误判成 miss（§10.2.2）
30. **Brier 的 partial 按 `outcome = 0.5` 计入**：`mean((confidence - verdict_score)^2)`，
    `verdict_score` 取 hit=1.0 / partial=0.5 / miss=0.0（§10.2.3）
31. **校准分桶补低置信桶 `[0.05, 0.5)`**：`confidence` 下限是 0.05，只统计 0.5+ 会静默丢弃
    大量低置信样本，导致校准曲线系统性偏高失真（§10.2.3）
32. **`unverifiable` 归 `status` 而非 `verdict`**，且只由证据门槛产生、**LLM 不得输出**——
    否则会变成逃避 miss 的软出口，污染命中率与 Brier（§10.2.2）

v1.8（M3a 验收后补丁）：
26. **手写预言 `falsifiable_criteria` 必填**：量化判据（`criteria`）可选，但判据**文本**必填——
    选模板时自动渲染、选"不设定"时向导追问一句话判据（§11.4.1）
27. **`category` 加入手写预言向导**：7 个序号选项 + 默认 `capability`（直接回车）。
    **理由：若手写预言全默认 capability，M3b 的"按 category 分组命中率"统计将失去意义**（§11.4.4）
28. **M3a 实证坑位归档**：Typer `invoke_without_command`、`expire_on_commit`、ruff B008、
    **json_schema/json_object 共用缓存键会串**（§18.4）

v1.7（M2 验收后补丁，★ 涉及依赖与架构调整）：
22. **移除 `openai` SDK 依赖，改为 httpx 直连**（§8.2）——它自带的 httpx 2.x 与项目 httpx 冲突、
    且导致 `respx` 无法 mock（M3 的 LLM 测试强依赖 mock 能力）
23. **json_schema 运行时自动降级**（§8.3）——json_schema 报 400 时自动重试 `json_object`，
    比让用户手动改配置友好得多
24. **SSOT 文档归属约定**：文档由项目负责人**出全量版本并覆盖**仓库内 `docs/`，避免两处漂移（§19.4）
25. **M3 拆为 M3a（生成）/ M3b（验证与统计）两个子阶段**（§16.1）

v1.6（M1 验收后补丁）：
18. **Import AI 改用官方可达 URL**：`importai.substack.com` 被墙 → 改用 `https://importai.net/feed`
    （301 → `jack-clark.net`，官方站，**且含全文**），因此从 `actions_only` 升为 `always`（§5.10 表、§18.3）
19. **arXiv `lookback_days: 7`**：arXiv Atom 的 `published` 是提交日且**索引滞后 3-4 天**，
    严格按 24h 窗口会永远采空。7 天是实测得出的合理默认（§18.3）
20. **RSS 内部改为并发拉取**：本地串行 8 个 feed 耗时 298s，M2 前需改为每 feed 一个任务（仍受全局并发 6 限制）（§18.3）
21. **M1 实证坑位归档**：arXiv 索引滞后、单 feed 失败拖垮整源、HN 全挂伪装成"没热点"、
    迁移未执行导致缺列、Trending 双通道、正则误匹配 SVG `<path>`、`--json` 被日志污染、HF fallback 语义（§18.3）

v1.5（M1 期间补充，回答"源不可达怎么办 / 能否增删源"）：
16. **新增 §5.11「数据源全景与可达性兜底」**：明确当前源清单、单源不可达的分级影响、
    **"任何单一源失效都不会导致功能废掉"的架构性保证**，以及 inbox/OAuth 等兜底手段
17. **新增 §5.12「数据源可扩展性」**：明确两级扩展门槛（RSS 类改 yaml / 新类型写 collector），
    并约定 **M1 结束时补写 `docs/新增数据源指南.md`**（借真实采集器总结最佳实践，同时倒逼接口规范化）

v1.4（M0 验收后补丁，★ 基于真实探测结果）：
12. **数据源按网络环境分级**：`availability: always | actions_only`（§5.10）
    ——M0 实测发现本地 WSL 与 GitHub Actions 的网络可达性**完全不同**（reddit/hf/importai 本地 DNS 被污染、Actions 可达），
    同一源在不同环境应有不同行为，避免"本地测不到就永久禁用高质量源"
13. **HF 镜像站策略**：配置仅预留 `fallback_endpoints: []` **空字段**，默认走官方 `huggingface.co`，国内用户自行填写（§5.4）
14. **中文源降级为「仅标题源」**：量子位仅 22 字摘要（≈只有标题），`title_only: true`、**不参与 TF-IDF 聚类**（摘要过短会污染聚类结果）（§5.7）
15. **M0 探测实证结论入档**：DNS 污染、gzip 损坏、GitHub/arXiv 本地成功率约 1/3 等（§18.2）

> **M0 已完成并通过验收**（tag `m0`，仓库 https://github.com/tochikoma777/aipulse）。
> v1.4 的补丁**必须在 M1 开工前应用**，因为它改变采集器的编写假设。

v1.3（第三轮：无 API 可用性，★ 重要架构变更）：
9. **引入三档运行模式 `off` / `hybrid` / `full`**，API 从"必需"降级为"可选增强"（§8.5）
   ——**没有 API key 也能用**，off 档具备采集、打分、聚类、趋势检测、手写预言+自动验证+校准统计的完整价值
10. **手写预言 `predict add` 提升为全档位核心能力**，采用「参数 + 交互式向导自动降级」双模交互（§11.4）
11. **预言新增可选「量化判据」字段**，带阈值的预言到期可零成本自动判定（§11.5）

> 至此 §19 的确认项已全部收敛，**无阻塞开工的待定项**。
> **v1.3 的设计原则：让 aipulse 在零 API 花费下依然是一个有价值的工具，API 只用来把它变得更好，而不是让它能用。**

| 项目 | 内容 |
|---|---|
| 项目代号 | `aipulse`，中文名「AI 脉搏」 |
| 命名由来 | **脉搏（Pulse）的三层隐喻，正好对应本项目的三段主线**：<br>① **把脉**＝每日采样信号（采集层：GitHub/arXiv/HF/HN/Reddit/RSS 的脉搏跳动）<br>② **诊断**＝从信号中读出含义（分析层：打分、聚类、实体频次变化）<br>③ **预后**＝判断病情走向（推演层：预言 + 到期回测）<br>且"脉搏"天然带周期节律，与日报/周报节奏契合；英文名短、好念、可作 CLI 名（`aipulse`） |
| 交付形态 | **CLI 核心 + 可选 Web UI**（CLI 是一等公民，Web 只是只读看板，M4 阶段再叠加） |
| 运行环境 | Windows 11 + WSL2(Ubuntu 22.04/24.04) + VSCode Remote-WSL + CodeBuddy |
| 语言版本 | Python 3.11+ |
| 存储 | SQLite（单文件，`data/aipulse.db`），后期可平滑迁移 Postgres |
| 许可证 | **MIT** |
| LLM 接入 | 云端 API，OpenAI 兼容协议，**默认 DeepSeek**（`deepseek-chat` 快模型 / `deepseek-reasoner` 强模型）；换厂商只改环境变量 |
| 目标数据源 | GitHub Trending、arXiv、HuggingFace Daily Papers、Hacker News、Reddit r/LocalLLaMA、RSS，外加手动投喂 inbox |
| 明确不做 | **微信公众号 / X（Twitter）自动抓取**——见 §1.2 与 §5.8 |
| 差异化亮点 | **可回测预言系统**（带置信度 + 到期自动验证 + 命中率/校准度公开统计） |

---

## 0. 给开发 Agent 的总纲（最高优先级，请先读）

1. **分阶段交付**：严格按 §16 的里程碑推进（**v1.1 重排：M4=发布与自动化，M5=深度推演；v1.6 拆 M3 为 M3a/M3b；**★ v1.13 新增 M6=每日学习增强，且 M6 插队到 M5 之前**）。当前顺序：**M0→M1→M2→M3a→M3b→M4→M6a→M6b→M5**。**禁止一次性生成整个项目**。每个里程碑结束必须跑通测试并向项目负责人汇报验收清单，得到确认后才能进入下一阶段。
2. **先探测，再编码**：M0 阶段必须先运行 `scripts/probe_sources.py`，把每个数据源的真实返回字段打印并存为 `tests/fixtures/*.json`。**严禁凭记忆或猜测编写字段解析代码**；所有解析逻辑必须基于真实响应快照。
3. **单源失败不影响全局**：任何一个采集器抛异常，只记录到 `source_runs` 表并告警，其余源继续跑，pipeline 不得整体崩溃。
4. **结构化输出优先**：所有 LLM 输出必须是 JSON，并用 Pydantic 模型校验；校验失败自动触发一次"修复重试"，再失败则记录错误并降级（跳过该条目，不中断）。
5. **可测试性**：所有网络调用走统一的 `HttpClient`（可被 `respx` mock）；所有 LLM 调用走 `LLMClient`（可被 `FakeLLM` 替换）。**核心逻辑必须能在完全断网、零 API 花费的情况下跑通测试**。
6. **成本护栏**：LLM 调用有每日预算上限（默认 2 CNY/日），超限自动降级（关闭辩论与长文，只保留简报与预言）。
7. **不要过度设计**：M0-M2 阶段不引入 embedding / 向量库 / 消息队列 / Docker。用 TF-IDF 做聚类，用 SQLite 做一切。
8. **提交规范**：Conventional Commits（`feat:` / `fix:` / `refactor:` / `test:` / `docs:`），每个里程碑一个 feature 分支。

---

## 1. 项目目标与产品边界

### 1.1 核心用户故事

- 作为 AI 从业者，我每天想花 10 分钟知道"今天 AI 圈发生了什么值得看的"，而不是刷 2 小时信息流。
- 我不只要"发生了什么"，更想要"这意味着什么"——有观点、有判断、有可验证的预言。
- 我想看到这个系统的预言到底准不准，而不是永远正确却无法证伪的废话。

### 1.2 明确不做（V1 边界，防止范围蔓延）

| 不做 | 原因 |
|---|---|
| 用户系统 / 登录 / 多租户 | 单机个人工具，无必要 |
| 实时推送（WebSocket、秒级刷新） | 日报/周报节奏足够，实时性无价值 |
| 全自动发布到社交平台 | 合规与风控风险，V1 只产出文件，人工决定发布 |
| 训练自己的模型 / 微调 | 与主线无关 |
| 全量网页正文抓取与全文索引 | 成本高收益低，V1 只用标题+摘要+少量正文 |
| **微信公众号 / X（Twitter）的抓取（含 RSS 桥）** | **v1.1 明确移除**。X 官方 API 已收费且额度极低、Nitter 大量关停；公众号无公开 API，第三方接口不稳定且有合规与版权风险。**替代方案 = 手动投喂 `inbox`**（§5.8），一条命令把看到的任意 URL 塞进系统参与分析与预言，完全合规且零维护成本 |

---

## 2. 总体架构

### 2.1 分层与数据流

```
┌───────────────────────────────────────────────────────────────────┐
│  L1 采集层  collectors/                                            │
│  github_trending │ arxiv │ hf_papers │ hackernews │ reddit │ rss  │
│  每个源独立限速、独立失败隔离、输出 RawItem                          │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼ RawItem[]
┌───────────────────────────────────────────────────────────────────┐
│  L2 归一化层  normalize/                                           │
│  字段清洗 → URL 规范化 → 内容指纹 → 去重(SimHash + 语义) → Item      │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼ Item[]  → SQLite: items / signals
┌───────────────────────────────────────────────────────────────────┐
│  L3 分析层  analysis/  （无 LLM，纯算法，零成本）                    │
│  热度打分 score.py │ 主题聚类 cluster.py │ 实体抽取 entities.py      │
│  → hot_score, topic_id, entity 频次变化                             │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼ 精选候选集（Top N + 每主题代表）
┌───────────────────────────────────────────────────────────────────┐
│  L4 推演层  reasoning/  （LLM 介入）                                │
│  brief(简报+点评) │ predictor(预言) │ verifier(回测)                 │
│  debate(多角色辩论) │ trend(周期长文)                                │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼ Brief / Prediction[] / DebateResult / TrendReport
┌───────────────────────────────────────────────────────────────────┐
│  L5 渲染层  render/                                                │
│  Markdown（主） │ HTML │ JSON（机器可读，供 Web/二次消费）            │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼ data/reports/YYYY/MM/DD/
┌───────────────────────────────────────────────────────────────────┐
│  L6 编排层  pipeline/daily.py  （CLI 命令 → 执行一条龙）             │
│  collect → normalize → analyze → brief → predict → render          │
└───────────────────────────────────────────────────────────────────┘
                            ▼
                    L7 可选 Web UI（M4，只读）
```

### 2.2 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| **SQLite 单文件** | 零运维、可 git 携带、备份就是拷文件；本项目数据量（约 500 条/日，一年 18 万条）远未触及 SQLite 上限 |
| **算法层与 LLM 层严格分离** | 打分/聚类不烧钱、可复现、可单测；LLM 只做"它擅长的判断与写作"，职责清晰，成本可控 |
| **Prompt 外置为模板文件** | 改 prompt 不改代码，可版本化、可 A/B、可人工审阅 |
| **统一 Item 抽象** | 所有源归一到同一 schema，新增源只需实现 `BaseCollector`，下游零改动 |
| **预言必须是结构化、可证伪的** | 这是项目灵魂，也是同类工具没有的东西；不可证伪的"预言"一律拒绝入库 |
| **全链路可离线跑通（Mock 模式）** | 便于开发、测试、CI，也让贡献者零成本上手 |

---

## 3. 技术选型

| 领域 | 选型 | 理由 / 备注 |
|---|---|---|
| 包管理 | **uv** | 比 pip 快 10-100 倍，锁文件可靠，WSL 下体验极好 |
| CLI 框架 | **typer** + **rich** | 类型注解即 CLI，输出美观，学习成本低 |
| HTTP | **httpx**（异步）+ 自研 `HttpClient` 包装 | 统一超时/重试/限速/缓存/UA；`respx` 可完美 mock |
| 数据校验 | **pydantic v2** | 同时用于 Item schema、配置、LLM 结构化输出校验与 JSON Schema 生成 |
| ORM | **SQLModel** + **alembic** | Pydantic + SQLAlchemy 二合一，模型只写一次 |
| 限流重试 | **tenacity** + 自研令牌桶 | 各源限速差异大，需按源配置 |
| 文本聚类 | **scikit-learn** TfidfVectorizer + 余弦相似度 | 无 API 成本、无模型下载，V1 足够；M5 后可选换 embedding |
| 中文分词 | **jieba** | 中文标题聚类前置处理 |
| Prompt | **Jinja2** 模板文件 | 见 §8 |
| 渲染 | Jinja2 → Markdown / HTML | 同一套数据多格式输出 |
| 日志 | **structlog** → JSON Lines | 便于事后分析与排查 |
| 测试 | **pytest** + **respx** + **pytest-asyncio** | 目标：核心模块覆盖率 ≥70% |
| 质量 | **ruff**（lint+format）+ **mypy** + **pre-commit** | 提交即检查 |
| 调度 | **GitHub Actions**（主）+ WSL cron（备） | Actions 免费且天然适合开源展示 |
| Web（M4） | **FastAPI** + Jinja2 模板 + **HTMX** | 无前端构建链，纯 Python，只读看板 |
| 向量（M5+可选） | **sqlite-vec** 或本地 bge-small（CPU） | 默认关闭，配置开启 |

> **明确不引入**：Docker（全阶段均不需要）、Celery / Redis（无异步任务需求）、LangChain（本项目 LLM 调用模式固定，自研 200 行更可控可测）。

---

## 4. 目录结构（Agent 必须严格按此创建）

```text
aipulse/
├── pyproject.toml                 # uv 管理，含 [tool.ruff]/[tool.mypy]/[tool.pytest]
├── README.md                      # 项目介绍 + 快速开始 + 截图
├── LICENSE                        # MIT
├── .env.example                   # 所有密钥与环境变量样例
├── .gitignore                     # data/ *.db *.env __pycache__ 等
├── .pre-commit-config.yaml
│
├── configs/
│   ├── default.yaml               # 主配置：llm / budget / pipeline / output
│   ├── sources.yaml               # 每个源的开关、限速、抓取参数、权重
│   └── scoring.yaml               # 热度打分权重（可调参）
│
├── prompts/                       # ★ 所有 prompt 外置，禁止硬编码进 .py
│   ├── brief/
│   │   ├── daily_brief.j2         # 生成每日简报
│   │   └── item_comment.j2        # 单条点评（为什么重要/对谁重要/下一步）
│   ├── predict/
│   │   ├── generate.j2            # 生成可证伪预言
│   │   └── verify.j2              # 到期验证预言
│   ├── debate/
│   │   ├── persona_bull.j2        # 乐观派
│   │   ├── persona_bear.j2        # 悲观/怀疑派
│   │   ├── persona_engineer.j2    # 工程落地派
│   │   ├── persona_investor.j2    # 商业/投资派
│   │   └── moderator.j2           # 主持人收敛
│   └── trend/
│       ├── weekly.j2
│       └── monthly.j2
│
├── src/aipulse/
│   ├── __init__.py
│   ├── cli/
│   │   ├── main.py                # typer app 入口，注册所有子命令
│   │   └── commands/              # 每个命令一个文件（collect/brief/predict/...）
│   ├── core/
│   │   ├── config.py              # pydantic Settings，读 yaml + env
│   │   ├── logging.py             # structlog 配置
│   │   ├── timeutil.py            # UTC 存储 / Asia-Shanghai 展示 / 时间窗计算
│   │   ├── errors.py              # 自定义异常层级
│   │   └── hashing.py             # canonical_url / content_hash / simhash64
│   ├── schema/
│   │   ├── items.py               # RawItem / Item / SourceMetrics / SourceEnum
│   │   ├── brief.py               # DailyBrief / Section / ItemComment
│   │   ├── prediction.py          # Prediction / Verdict
│   │   ├── debate.py              # DebateResult / PersonaOpinion
│   │   └── trend.py               # TrendReport / TopicEvolution
│   ├── collectors/
│   │   ├── base.py                # BaseCollector 抽象基类（async）
│   │   ├── registry.py            # 源注册与发现
│   │   ├── github_trending.py
│   │   ├── arxiv.py
│   │   ├── hf_papers.py
│   │   ├── hackernews.py
│   │   ├── reddit.py
│   │   ├── rss.py
│   │   └── inbox.py               # 手动投喂（本地文件/命令行）
│   ├── normalize/
│   │   ├── clean.py               # HTML 清洗、空白规整、语言检测
│   │   └── dedup.py               # 三级去重
│   ├── store/
│   │   ├── db.py                  # engine / session / init
│   │   ├── models.py              # SQLModel 表定义
│   │   ├── repo_items.py          # upsert / 查询 / 时间窗统计
│   │   ├── repo_predictions.py
│   │   ├── repo_runs.py           # source_runs / pipeline_runs / llm_usage
│   │   └── migrations/            # alembic
│   ├── llm/
│   │   ├── base.py                # LLMClient Protocol + FakeLLM（测试用）
│   │   ├── openai_compat.py       # OpenAI 兼容实现（默认）
│   │   ├── cache.py               # prompt_hash → response，SQLite
│   │   ├── budget.py              # 每日预算与降级
│   │   ├── structured.py          # JSON Schema 约束 + 校验 + 修复重试
│   │   └── prompt.py              # Jinja2 加载器 + 变量注入
│   ├── analysis/
│   │   ├── score.py               # 热度打分
│   │   ├── cluster.py             # 主题聚类
│   │   ├── entities.py            # 实体抽取与频次统计
│   │   └── signals.py             # 指标快照与增速
│   ├── reasoning/
│   │   ├── brief.py
│   │   ├── predictor.py
│   │   ├── verifier.py
│   │   ├── debate.py
│   │   └── trend.py
│   ├── render/
│   │   ├── markdown.py
│   │   ├── html.py
│   │   └── json_out.py
│   ├── notify/                     # v1.2：只实现 file，其余渠道仅预留
│   │   ├── base.py                 # Notifier Protocol
│   │   └── file.py                 # FileNotifier（唯一默认实现）
│   ├── pipeline/
│   │   ├── daily.py               # 每日流水线编排
│   │   ├── weekly.py
│   │   └── context.py             # 贯穿全流程的 RunContext
│   ├── web/                       # M4 可选
│   │   ├── app.py                 # FastAPI
│   │   └── templates/
│   └── utils/
│       ├── http.py                # HttpClient：限速/重试/缓存/UA/超时
│       └── text.py                # 截断、token 粗估、语言检测
│
├── scripts/
│   ├── probe_sources.py           # ★ M0 必跑：探测所有源真实返回
│   ├── backfill.py                # 历史补数据
│   └── export_site.py             # 导出静态站点（M4）
│
├── tests/
│   ├── fixtures/                  # ★ probe 产出的真实响应快照
│   │   ├── github_trending.html
│   │   ├── arxiv_atom.xml
│   │   ├── hf_daily_papers.json
│   │   ├── hn_search.json
│   │   ├── reddit_top.json
│   │   └── rss_feed.xml
│   ├── unit/
│   └── integration/
│
├── data/                          # .gitignore 忽略
│   ├── aipulse.db
│   ├── cache/http.sqlite
│   ├── reports/YYYY/MM/DD/
│   └── inbox/                     # 手动投喂文件落地目录
│
├── docs/
│   ├── 架构说明.md
│   ├── 数据源手册.md               # 每个源的字段、限速、失效应对
│   ├── 预言系统说明.md
│   └── 开发日志.md                 # Agent 每阶段追加记录
│
└── .github/workflows/
    ├── daily.yml                  # 定时跑流水线 + commit 报告
    └── ci.yml                     # lint + test
```

---

## 5. 采集层设计（L1）

### 5.0 统一抽象

```python
# src/aipulse/collectors/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from aipulse.schema.items import RawItem, SourceConfig

class BaseCollector(ABC):
    source: str                       # "github_trending" | "arxiv" | ...
    display_name: str                 # 中文展示名

    def __init__(self, cfg: SourceConfig, http: HttpClient): ...

    @abstractmethod
    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        """抓取 [since, until) 窗口内的数据。禁止在此方法内写库。"""

    async def healthcheck(self) -> bool:
        """轻量连通性检查，供 aipulse doctor 使用。默认实现一次最小请求。"""
```

**铁律**：
- 采集器只负责"拿到数据 + 转成 RawItem"，**不做去重、不写库、不调用 LLM**。
- 所有 HTTP 请求必须走注入的 `HttpClient`，**禁止在采集器内直接 `httpx.get`**。
- 每个采集器必须处理"源返回空"的情况，返回空列表并记录 warning（不得抛异常）。

### 5.1 RawItem 统一 schema

```python
class SourceEnum(str, Enum):
    GITHUB_TRENDING = "github_trending"
    ARXIV = "arxiv"
    HF_PAPERS = "hf_papers"
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    RSS = "rss"
    INBOX = "inbox"

class RawItem(BaseModel):
    source: SourceEnum
    external_id: str            # 源内唯一 ID（repo full_name / arxiv id / HN objectID / 文章 URL hash）
    title: str
    url: str                    # 规范化后的规范 URL
    summary: str = ""           # 摘要/描述（清洗后）
    author: str | None = None
    published_at: datetime      # 源给出的发布时间（UTC）；无则用抓取时间
    metrics: dict = {}          # 源特有指标，见各源说明
    tags: list[str] = []
    language: str | None = None # 代码语言 or 自然语言
    extra: dict = {}            # 源特有附加信息（如 arxiv categories、repo topics）
    raw: dict | None = None     # 原始响应片段（调试用，入库时可选丢弃以省空间）
```

### 5.2 GitHub Trending

- **主要方式**：抓取 `https://github.com/trending?since=daily`（可选 `&l=python`）。
  - 解析字段：`full_name`、描述、`language`、`stars_total`、`stars_in_window`、`forks`、`built_by`。
  - **风险**：HTML 结构不稳定，GitHub 随时可能改 class 名；历史上 weekly/monthly 列表曾出现长时间为空。
  - **应对**：① 解析器用稳定的结构化特征（`article.Box-row` 下 `h2 a` 取 repo 名）而非易变 class；② 有 `tests/fixtures/github_trending.html` 快照测试；③ 结果为空或条数 <5 时自动降级到方式二并记录告警。
- **降级/交叉验证方式（强烈建议同时启用）**：GitHub Search API
  - `GET https://api.github.com/search/repositories?q=created:>{date}&sort=stars&order=desc&per_page=50`
  - 也可按 topic 搜：`q=topic:llm+created:>{date}`、`q=llm+in:name,description+created:>{date}&sort=stars`
  - 带 `GITHUB_TOKEN` 时 30 req/min；无 token 10 req/min。**必须配置 token 环境变量（可选但强烈建议）**。
  - 注意：Search API 排序的是**总 star 数**，不能反映"增速"。增速靠 §5.2 的 `signals` 快照自己算。
- **星标增速（velocity）**：对采集到的 repo，每次采集写入 `signals` 表一条 `(entity_type=repo, entity_key=full_name, metric=stars, value=stars_total, ts=now)`，从而算出 `Δstars/Δt`。这是判断"真正在涨"还是"老项目常青"的唯一可靠办法，**是本项目的关键增值点**。
- **限速**：trending 页面 1 次/6 小时足够（GitHub 本身约 6 小时更新一次）；Search API 按 token 限额。

### 5.3 arXiv

- 端点：`http://export.arxiv.org/api/query`
- 例：`search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=200`
- 也可用日期区间：`cat:cs.LG+AND+submittedDate:[202610100000+TO+202610110000]`
- 解析：Atom XML，建议用 `feedparser`；字段：`id`(→2401.12345)、`title`、`summary`、`authors`、`published`、`tags`(categories)、`link`(pdf)。
- 关注分类建议（可在 `sources.yaml` 配置）：`cs.AI`、`cs.LG`、`cs.CL`、`cs.CV`、`cs.MA`、`stat.ML`、`cs.IR`。
- **限速：硬限制 3 req/s**（超过返回 503，可能临时封 IP）。实现：该源 `rate_limit: 3/s`，请求间强制 `sleep ≥ 3s`，并带描述性 `User-Agent`。
- 数量控制：每日 cs.LG 新增数百篇，V1 只取**按关键词过滤 + 引用/热度粗排后的 Top N（默认 60）**，关键词列表可配置（如 LLM、agent、multimodal、diffusion、inference、RLHF...）。

### 5.4 HuggingFace Daily Papers

- 端点：`GET https://huggingface.co/api/daily_papers?date=YYYY-MM-DD`（公开只读，无需 token；可选 `&limit=50`、`&p=0`/`&page=1`、`&sort=publishedAt` 或 `trending`）
- 详情：`GET https://huggingface.co/api/papers/{arxiv_id}` → 摘要、upvotes、AI 生成摘要、关联 GitHub repo
- 关联资源：`GET https://huggingface.co/api/arxiv/{arxiv_id}/repos` → 该论文的 models/datasets/spaces（**很有价值：能判断论文是否有代码、是否可复现**）
- 模型趋势（可选，作为"模型发布"信号）：`GET https://huggingface.co/api/models?sort=trending&filter=text-generation&limit=20`
- **镜像与可达性（v1.4）**：
  - M0 实测：本地 WSL 下 `huggingface.co` **DNS 被污染**（解析到无关网段后连接超时）；`hf-mirror.com` 可用且 schema 一致（实测拿到 50 条真实数据）。
  - **配置只预留空字段，默认走官方**：
    ```yaml
    hf_papers:
      availability: actions_only
      fallback_endpoints: []      # 国内用户可自行填 ["https://hf-mirror.com"]
    ```
  - **理由：开源项目的默认配置必须走官方源。** 第三方镜像的可信度、稳定性、更新延迟均不受控，
    不应由项目替所有用户做这个决定。但把字段留出来，国内用户填一行即可，比改代码友好得多。
  - 探测脚本（`scripts/probe_sources.py`）中**允许**自动尝试 fallback——那是诊断工具，不是生产默认行为。
- **去重关键**：HF Daily Papers 与 arXiv 高度重叠，必须以 `arxiv_id` 做交叉去重（`dedup` 层的 `cross_source_key`）。arXiv 提供"有没有"，HF 提供"社区是否买账(upvotes)"——两者应**合并为一条 Item**，而非两条。

### 5.5 Hacker News

- 端点（Algolia，免密钥）：`https://hn.algolia.com/api/v1/search_by_date`
- 参数：`query=<关键词>&tags=story&numericFilters=created_at_i>{ts},points>{N}&hitsPerPage=50`
- 关键词配置化：`AI`、`LLM`、`GPT`、`Claude`、`agent`、`open source model`、`inference` 等（多关键词串行查，去重）。
- 字段：`objectID`、`title`、`url`、`author`、`points`、`num_comments`、`created_at_i`、`story_text`。
- 评论（可选，`--with-comments`）：`GET https://hn.algolia.com/api/v1/items/{id}` 一次拿整棵评论树，用于"舆论情绪"分析 —— **V1 仅对 Top 3 故事开启**，控制成本。
- 备选：官方 Firebase API `https://hacker-news.firebaseio.com/v0/item/{id}.json`（拿单条最新分数）。

### 5.6 Reddit r/LocalLLaMA

- **必须 OAuth**：Reddit Data API 要求注册应用拿 `client_id/client_secret`，走 `https://www.reddit.com/api/v1/access_token` 取 token，100 QPM（按 client_id 计，10 分钟滑动平均）。
- 端点：`GET https://oauth.reddit.com/r/LocalLLaMA/top?t=day&limit=50`
- **UA 强制**：必须是 `<platform>:<app_id>:<version> (by /u/<username>)` 格式，否则会被严厉限流。
- **v1.2 决策：V1 走免认证 RSS，`mode: rss` 为默认；OAuth 代码路径在 M1 预留接口但不实现。**
  - RSS 端点：`https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day`
  - 已知限制：约 25 条、无 score 字段、按 IP 限流。
  - **缺失 score 的补偿办法**（Agent 必须实现，不是简单置 0 了事）：
    ① `metrics.score = 0` 但保留 `metrics.comments`（可从 RSS 内容或条目顺序推断）；
    ② 该源在 `scoring.yaml` 中的 `source_weight` 下调（0.7 → 0.55），并把 `engagement` 分项的权重让渡给 `freshness` 与 LLM 判断；
    ③ 用条目在 RSS 列表中的**排名位次**作为热度代理信号：`rank_score = (N - rank) / N`。
  - **升级触发条件（M1 验收时评估）**：若 r/LocalLLaMA 条目长期在简报中占比偏低或质量明显不如其他源，再决定是否申请 OAuth。OAuth 需注册应用、承担 Responsible Builder Policy 义务、多一套密钥管理——**不要提前付这个成本**。
- **合规要求（两种模式都要遵守）**：不存储已删除内容（定期清理源端已删除的条目）、不缓存用户身份信息、README 明确标注数据来源。
- 建议子版（可配置）：`LocalLLaMA`（主）、`MachineLearning`（备）。

### 5.7 RSS（新闻/博客）—— v1.2 定为「英文主干 + 中文补充」

- 通用 RSS/Atom 采集器，源列表在 `configs/sources.yaml` 中声明（`feedparser` 解析）。
- **源分层策略**：

| 层级 | 源 | 定位 |
|---|---|---|
| **主干（英文）** | Simon Willison's Blog、Import AI、Latent Space、Anthropic 官方博客、OpenAI 官方博客、DeepSeek 官方博客、HuggingFace Blog | RSS 极其稳定、信噪比高、几乎无营销稿，**新闻板块的基本盘** |
| **主干（英文）** | The Verge AI、TechCrunch AI、Ars Technica | 补充产业与产品动态 |
| **补充（中文）** | 机器之心、量子位、36氪 AI | 国内视角与工程实践；**失效视为可接受的降级**，不阻塞流水线 |

- **中文源的现实问题（M0 探测实测结论，v1.4 更新）**：
  - **实测结果**：机器之心、36氪 的 feed **已下线或返回 HTML**（非 RSS）；**仅量子位可用，但摘要仅 22 字（≈只有标题）**。
  - **v1.4 决策：接受现状，把中文源定义为「仅标题源」**——
    ```yaml
    - {name: 量子位, url: "https://www.qbitai.com/feed", tier: optional, title_only: true}
    ```
  - **三条配套处理**（Agent 必须实现）：
    ① `title_only: true` 的源**不参与 TF-IDF 聚类**——摘要过短会导致该源条目与任意条目都算出低相似度，
       污染聚类结果（要么自成一簇、要么错误并入他簇）。
    ② `source_weight` 降至最低档（0.35），热度主要靠排名位次与 LLM 判断。
    ③ 简报的"产业与新闻"板块实质以英文主干为主，中文源仅作补充视角。
  - **通用应对（保留）**：`optional: true` 的源失效时**只告警不报错**，不影响 pipeline 退出码；为每个源准备 1-2 个备用 feed URL。
- **探测要求**：M0 阶段 `probe_sources.py` 必须对**每一个** RSS 源单独发请求并记录：HTTP 状态、条数、是否含正文、更新时间。结论写入 `docs/数据源手册.md`，失效源直接从 `sources.yaml` 移除或替换。
- 输出 Item 时 `metrics` 为空，热度主要由 `source_weight` + 排名位次 + LLM 判断贡献。

### 5.8 微信公众号 / X（Twitter）—— v1.1 已移除

**决策：不实现任何针对微信公众号 / X 的抓取、RSS 桥或第三方接口集成。** 理由：

| 源 | 为什么放弃 |
|---|---|
| X/Twitter | 官方 API 已转为付费且免费额度极低；Nitter 公共实例大量关停，自建需维护代理与反爬，投入产出比极差 |
| 微信公众号 | 无任何公开 API；第三方接口不稳定、随时失效，且转载其内容存在明确的版权与合规风险 |
| RSS 桥（RSSHub 等） | 需要自建并长期运维一个服务，与"个人单机工具"的定位冲突；且桥本身仍依赖上述不稳定上游 |

**唯一替代通道 = 手动投喂 `inbox`（M1 必须实现，成本极低、价值高）**：

```bash
aipulse inbox add <url> --note "自己的一句话观察"   # 抓取 URL 标题+摘要入库，source=inbox
aipulse inbox add-file data/inbox/notes.md          # 批量从本地 markdown 导入
```

- 你在微信、X、小道消息、线下聊天里看到的任何东西，一条命令就能塞进系统，照样参与打分、聚类、简报点评与预言生成。
- 完全合规、零维护成本、无失效风险。
- `inbox` 条目的 `source_weight` 默认 0.5（低于自动源），但它携带的 `--note`（你自己的观察）会在简报与推演中被作为高价值上下文使用。

> **对 Agent 的要求**：`collectors/` 下**只有** 6 个自动源采集器（github_trending / arxiv / hf_papers / hackernews / reddit / rss）+ 1 个 inbox。**不得新增任何微信或 X 相关的采集器、配置段或环境变量**。若项目负责人后续改变主意，通过新增一个标准 RSS 源即可（通用 RSS 采集器已覆盖），不需要改架构。

### 5.11 数据源全景与可达性兜底（v1.5 新增，回答"源不通是不是就废了"）

#### 5.11.1 当前数据源全景（M0 实测后确认的 7 类入口）

| # | 源 | 类型 | 提供什么信号 | 本地 | Actions | 唯一性 |
|---|---|---|---|---|---|---|
| 1 | **GitHub Trending** | API + HTML | 开源项目热度、**star 增速** | △ 不稳 | ✅ | 唯一的"工程落地热度"信号 |
| 2 | **arXiv API** | API | 论文预印本、研究前沿 | △ 不稳 | ✅ | 唯一的"学术一手"信号 |
| 3 | **HF Daily Papers** | API | 论文**社区认可度**(upvotes)、是否开源代码 | ❌ DNS | ✅ | 判断"论文是否真被买账" |
| 4 | **Hacker News** | API(Algolia) | 技术社区舆论、讨论热度 | ✅ | ✅ | 唯一的"高质量开发者舆论" |
| 5 | **Reddit r/LocalLLaMA** | RSS | 一线玩家真实反馈、草根实践 | ❌ | ✅ | 唯一的"玩家视角" |
| 6 | **RSS（9 个英文 + 1 中文）** | RSS/Atom | 产业动态、官方发布、名家观点 | 部分 ✅ | ✅ | 唯一的"产业/官方"信号 |
| 7 | **inbox 手动投喂** | 手动 | 任意来源 + 你自己的观察 | ✅ | ✅ | **永不失效的兜底通道** |

#### 5.11.2 核心结论：任何一个源挂掉，功能都不会废

**这是架构层面的保证，不是运气。** 三条机制叠加：

**① 单源失败隔离（§5.9）**
每个源独立 try/except，失败只写 `source_runs` 表 + 告警，其余源照常完成，pipeline 退出码不受影响。
实测：M0 探测时 reddit / HF / importai 三个源全部不可达，探测脚本依然完成了其余 8 个源并产出了完整报告。**这就是这套机制有效性的一次真实验证。**

**② 信号冗余：没有哪个"能力"依赖单一源**

| 能力 | 需要的信号 | 可用源 | 挂掉一个会怎样 |
|---|---|---|---|
| 每日简报 | 任意热点条目 | 7 类全部 | **完全无感**——少一个源只是少几条候选，Top N 照样排得出来 |
| 主题聚类 | ≥2 个条目语义相近 | 任意源 | 无感 |
| 开源项目板块 | GitHub 数据 | GitHub Trending / Search API（双通道） | Trending HTML 改版 → 自动降级 Search API |
| 论文板块 | arXiv ID + upvotes | arXiv + HF（**互为备份**，同一篇论文） | 挂一个，另一个仍能提供该论文（只是少 upvotes 或社区热度） |
| 社区舆论板块 | 讨论热度 | HN + Reddit | 挂一个仍有另一个 |
| 产业新闻板块 | RSS | 10 个 feed，**英文主干 9 个** | 挂 1-2 个 feed 完全无感 |

**结论：只有"辩论"和"周期长文"会在数据源极度贫瘠时质量下降**（因为需要足够的证据包做推演），
而且这两个功能本来就在 M5、且只在 `full` 档启用。**采集、打分、聚类、简报、预言、回测这条主链路，不受任何单一源影响。**

**③ inbox 是永不失效的兜底**
哪怕所有外网源全断，你依然可以 `aipulse inbox add <url>` 手动投喂——**这条链路不依赖任何外网 API**，
打分、聚类、简报、预言、验证、记分板全部照常工作。

#### 5.11.3 源不可达时的分级应对手册

| 场景 | 表现 | 应对 |
|---|---|---|
| 临时抽风（超时/429/503） | 偶发失败 | `tenacity` 退避重试 3 次；HTTP 缓存保留上次成功结果 |
| 长期限速 | 频繁 429 | 调低该源 `rate_limit`；降低采集频率 |
| 端点改版（GitHub HTML） | 解析出 0 条 | 快照测试报警 → 自动降级 Search API（已实现双通道） |
| 域名污染 / 被墙 | 连接超时 | 标 `actions_only`，Actions 环境采集；或配代理 |
| feed 下线 | 404 / 返回 HTML | `optional` 源静默跳过；`core` 源报警并尽快替换 URL |
| 源彻底废弃 | 长期不可用 | 从 `sources.yaml` 移除或 `enabled: false`，见 §5.12 |

**判断"要不要修"的标准**：看该源是否是某类信号的**唯一提供者**（见 5.11.1 最后一列）。
若是唯一的（如 GitHub 是唯一工程热度源），优先修；若有冗余（如 arXiv 与 HF），可以先放着让备份顶上。

### 5.13 事件型 vs 状态型数据源（v1.14，★ 重要设计修正）

**问题**：REA（morluto/rea）15 号日报里有，16/17 号消失——而它其实每天都在榜。

**根因**：两类数据源的时间语义根本不同，此前被混为一谈。

| 类型 | 源 | 时间语义 | 例子 |
|---|---|---|---|
| **事件型** | arXiv / HF / HN / RSS | `published_at` = 事件发生时刻，**固定不变** | 论文 10-15 发表就永远是 10-15 |
| **状态型** | **GitHub Trending** | **无发布时间**，只有"此刻是否在榜" | REA 此刻在榜 = 当下热点 |

Trending 页面是一份**当前快照**，不含任何时间戳。采集时给它赋了首次采集时刻，
之后跨天重复采集通过 `content_hash` upsert 合并——**合并保留首次发现时间**。于是：

```
10-15  首次采集 → 时间 = 10-15 → 进入 15 号窗口 ✅
10-16  仍在榜，再次采集 → upsert 合并，时间仍是 10-15 → 滑出 16 号窗口 ❌
10-17  同理 ❌ 永久消失
```

**修复**：

| 字段 | 含义 |
|---|---|
| `first_seen_at` | **首次发现**，只在第一次采集时设置，之后 upsert 不更新 |
| `last_seen_at` | **最近一次被采集到**，每次 upsert 都更新 |
| `published_at` | 事件型源的发布时间（状态型源为空） |

#### ★★ 时间语义有**三态**不是两态（v1.15 修正）

v1.14 只定义了 event / state 两态，**这是不完整的**，导致一个严重副作用：
arXiv/HF 按 `published_at` 过滤时，**因索引滞后 3-4 天而大量丢失**——
M1 为了解决这个问题设了 `lookback_days: 7`（采集过去 7 天），
但过滤时只保留"24h 内发布的"，**等于采了却不用，白采**。

| 语义 | 依据字段 | 适用源 | 为什么 |
|---|---|---|---|
| **`event`** | `published_at` | Hacker News / RSS | 有准确发布时间**且不滞后**。某天采集失败就是漏了，这是正确行为 |
| **`state`** | `last_seen_at` | GitHub Trending | 无发布时间，关心"此刻是否仍在榜"；连续在榜应连续出现 |
| **`discovery`**（v1.15 新增） | **`first_seen_at`** | **arXiv / HF Daily Papers** | 索引滞后使 `published_at` 不可用；<br>**读者关心的是"今天新发现了什么"，不是"投稿日期是不是今天"** |

**`discovery` 不会造成重复**：`first_seen_at` 只在首次采集时设置，之后 upsert 不更新，
所以一篇论文只在"首次发现那天"出现一次——即使它连续多天都出现在 arXiv 的回看结果里。

**一句话判据**：
> 用 `published_at` 的前提是"发布时间 ≈ 我们能看到它的时间"。
> **只要存在索引滞后，就必须改用 `first_seen_at`。**

配置：`sources.*.time_semantics: event | state | discovery`。

#### 简报每板块条数上限（v1.15）

`brief.max_items_per_section: 10`（可配置）。超出部分显示「另有 N 条」。

**理由**：24 条论文全列出来违背本项目"帮你果断放弃大部分"的核心原则。
**一个让人无从下手的日报，和没有日报差别不大。**

#### 「一句话」列的降级态（v1.15）

无 LLM 时该列填的是**原始摘要截断**，容易让读者误以为是模型生成的判断。
列名改为**「要点」**，兼容两种状态：有 LLM 时是模型判断，无 LLM 时是摘要截断。

**附带收益**：可新增「**连续在榜 N 天**」信号——比单日热度更能说明一个项目是真火。
这与 `signals` 表已有的 star 快照追踪在概念上也终于一致了。

**为什么必须修**：它造成"昨天看到想跟进的项目今天不见了"，
让使用者怀疑系统漏报——这种怀疑一旦产生，工具价值大打折扣。

### 5.14 ★ 今日 Trending vs 持续追踪（v1.18，P0）

#### 问题：一个"很火的项目"消失了，是 bug 吗

用户反馈：REA（morluto/rea）**这么火的项目没统计进来不合理**。

**先分清两种情况，不要一上来就改代码**：

| 情况 | 判定依据 | 处理 |
|---|---|---|
| **A. 仍在榜但没进日报** | 本次采集的 trending 条目里有它，日报却没有 | **真 bug**，修 |
| **B. 已掉榜** | 本次采集的 trending 条目里根本没有它 | **正确行为**（Trending 是快照，掉榜就该消失） |

**即便确认是 B，用户的诉求依然成立**。真实诉求不是"它必须每天出现"，而是：

> **一个我标记为"很火、想持续跟进"的项目，不该因为某天没上榜就彻底消失。**

#### 解法：把两个概念分开

| 概念 | 语义 | 数据来源 | 时间语义 |
|---|---|---|---|
| **今日 Trending** | 此刻在榜（快照） | `items` | `state`（`last_seen_at`） |
| **★ 持续追踪** | 值得长期关注的项目 | **`signals` 表的 star 快照序列** | 序列，与"在榜"无关 |

**★ 关键洞察**：`signals` 表**从 M1 起就在持续记录所有采集过的 GitHub 项目的 star 快照**
（每天写 `metric=stars`）——**REA 的 star 数据一直在被追踪，只是没在日报里展示**。

所以解法不是"强行让掉榜项目进 Trending"（那会破坏快照语义），
而是**把已经存在的数据展示出来**。

#### ★★ 诊断结案（2026-10-17 真实数据）

| 证据 | 值 |
|---|---|
| 17 号采集的 trending 条目 | **7 条，没有 REA** |
| `collect.failed_sources` | **0**（7 源全通，不是采集失败） |
| REA 最后被采到 | 2026-10-16T01:03Z |
| 17 号窗口起点 | 2026-10-16T08:41Z |
| 差值 | **早约 7.6 小时** → 按 `state` 语义正确排除 |

**结论：真掉榜，不是 bug。M6a 的修复行为完全正确。**

#### ★ 但这次诊断暴露了一个更重要的事实

REA 的 `signals` 快照序列：

```
first_ts:  2026-10-15T14:47:30Z   261752 stars
last_ts:   2026-10-16T01:03:59Z   270369 stars
delta:     +8617（约 10 小时）      status: ok
```

> **一个 27 万 star、10 小时涨了 8617 的项目，因为掉榜就在日报里彻底消失了。**

这不是系统的错（快照语义正确），**但确实漏掉了一条用户该知道的信息**。
而 `signals` 表从 M1 起就记着这些数据——**只是没展示**。

#### 实现（P0，两项）

**任务 1 · 开源项目表格增加「★ 总数」与「增量」两列**

- 数据源：`signals` 表
  （⚠️ 正确列名 `entity_type` / `entity_key` / `metric` / `value` / `ts`）
- **★ 增量只显示绝对增量，不显示每小时速率**
  - `ok` → 显示 `+8617`
  - `insufficient`（间隔 <6h）→ **给绝对增量，但不给速率**
    （M4 已定：绝不显示被短窗口放大的离谱数字，如曾出现的"日增 29951"）
  - `cold_start`（仅一个快照）→ 总数照常，增量 `—`
  - 无数据 → `—`
- 取**窗口内最新的两个快照**，不要用全表首末（否则混入多天前老数据）

**任务 2 · 新增「📈 增速榜（追踪中）」区块**

- 取**所有 repo 的 star 增量**，**排除今日 trending 已展示的**（避免重复）
- **★ 排序按「日均增量」**（`delta / window_hours × 24`），**不按绝对增量**（v1.20）
  —— 不同项目窗口长度不同，按绝对值排不可比。日均相同再按绝对增量、`entity_key` 兜底保证稳定
- **显示仍给绝对增量 + 窗口**（`+8617 / 10h`）；日均只用于排序，不作为显示值
- Top 5（可配置 `brief.velocity_board_top_n`），仅纳入 `status=ok`（窗口 <6h 的 `insufficient` 排除）
- 每行：`项目名 · ★总数 · +增量`
- 开关 `brief.velocity_board_enabled`（默认开）；**0 条时不显示区块**
- **预期效果**：REA 会以 `morluto/rea · ★270369 · +8617` 出现，**它不再消失**

**★ 与设计原则的一致性**：
不要为了"让掉榜项目出现"去改 trending 的 `state` 语义——**那会破坏快照模型**。
正确做法是**用另一套数据（star 序列）在另一个区块呈现**，两个概念并存不冲突。

#### 为什么这个改动值得做

1. **star 总数 + 增量是判断项目价值最直接的指标**，比"今天在不在榜"信息量大得多
   （榜单是滚动的，有偶然性）
2. **`signals` 数据已存在**，改动主要在展示层
3. 它**补上了快照型源的天然缺陷**（掉榜即消失）
4. 顺带满足用户明确提出的 P0 需求

### 5.12 数据源可扩展性（v1.5 新增，回答"以后能不能加源"）

**答案：能，而且分两个难度等级。**

| 等级 | 适用 | 操作 | 耗时 |
|---|---|---|---|
| **L1：改配置** | 新增/删除/替换任何 **RSS 或 Atom** 源 | 编辑 `configs/sources.yaml` 的 `rss.feeds` 列表，增删一行 | **1 分钟，零代码** |
| **L2：写模块** | 新增**全新类型**的源（Product Hunt、微博、YouTube 频道、某个新 API） | 在 `collectors/` 下新建一个继承 `BaseCollector` 的类，实现 `fetch()`，在 `registry.py` 注册 | 约 30-60 分钟 |

**为什么 RSS 类这么简单**：`rss.py` 是通用采集器，`feeds` 列表里每一项只需 `name` / `url` / `tier`，
新增任意 RSS 源不需要写任何解析代码——**这是当初坚持"统一 Item 抽象 + 通用 RSS 采集器"的回报**。

**L2 之所以只需 30-60 分钟**，是因为 `BaseCollector` 把所有脏活都封装好了：

```python
class MyNewCollector(BaseCollector):
    source = "my_source"
    display_name = "某某源"

    async def fetch(self, since, until) -> list[RawItem]:
        # 你只需要做两件事：1. 拿数据  2. 转成 RawItem
        # 限速、重试、缓存、代理、超时、失败隔离 —— 全部由 HttpClient 与基类处理
        ...
```

然后 `registry.register(MyNewCollector)` 即可。**下游（去重、打分、聚类、简报、预言）零改动**——
它们只认 `Item`，不认具体源。

**删除源**：`enabled: false`（临时）或从配置/registry 移除（永久）。**不影响历史数据**。

**替换源**：改 URL 即可；若新源字段不同，只改该 collector 的 `fetch()` 解析部分（约 10 行）。

> **约定：M1 结束时补写 `docs/新增数据源指南.md`。**
> 选这个时机的理由：① 6 个真实采集器刚写完，有真实例子可引用，指南才不是空谈；
> ② 写指南的过程会**倒逼 M1 把 `BaseCollector` 接口写得规范清晰**——这是本项目对外部贡献者最友好的入口，
> 也是开源后最容易吸引 PR 的地方（"我加了个 XX 源"是最常见的贡献形式）。

### 5.10 数据源可用性分级（v1.4 新增，M1 必读）

**背景（来自 M0 真实探测）**：本地 WSL 环境与 GitHub Actions 环境的网络可达性**完全不同**。
若按"本地测不到 = 源不可用"来写采集器，会永久丢失一批在 Actions 里其实完全可用的高质量源。

| 源 | 本地 WSL（无代理） | GitHub Actions | 分级 |
|---|---|---|---|
| GitHub Trending / Search API | 可用但不稳定（约 1/3 成功率） | 稳定可用 | `always` |
| arXiv API | 可用但不稳定 | 稳定可用 | `always` |
| HF Daily Papers | **DNS 污染**，不可达 | 可达 | `actions_only` |
| Hacker News Algolia | 可用 | 稳定可用 | `always` |
| Reddit RSS | **不可达** | 可达 | `actions_only` |
| RSS · Import AI | ✅ 可达（v1.6 改用 `importai.net/feed`，官方站且含全文） | 可达 | **`always`**（v1.6 升级） |
| RSS · 其余英文主干 | 可用 | 稳定可用 | `always` |
| RSS · 中文（量子位） | 可用，仅标题 | 可用 | `always`（`title_only: true`） |

**配置字段**：

```yaml
sources:
  reddit:
    availability: actions_only   # always | actions_only
  hf_papers:
    availability: actions_only
    fallback_endpoints: []       # 见 §5.4，默认空
```

**行为约定（Agent 必须实现）**：

| 场景 | `always` | `actions_only` |
|---|---|---|
| 本地运行（未设 `AIPULSE_ENV=actions`） | 正常采集，失败计入 `source_runs` 失败统计 | **跳过采集**，写入 `source_runs.status = 'skipped_offline'`，**不计入失败**，退出码不受影响 |
| Actions 运行（`AIPULSE_ENV=actions`） | 正常采集 | **正常采集**，失败按常规处理 |
| `aipulse doctor` | 正常探针 | 本地显示 ⏸「本环境不可达，将在 Actions 启用」而非 ❌ |

**为什么必须现在定**：M1 要写 6 个采集器。若没有这个分级，Agent 会因为"reddit 本地测不到"而在采集器里写死跳过逻辑，
或反过来把本地失败当 bug 反复排查——两种都是错的。

### 5.9 采集执行与容错

- 并发：`asyncio.gather`，每个源一个任务；全局并发上限 6，每源独立令牌桶。
- 超时：连接 5s、读取 20s；总任务超时 300s。
- 重试：`tenacity`，最多 3 次，指数退避 + 抖动；仅对 429/5xx/超时重试，4xx（除 429）不重试。
- HTTP 缓存：`data/cache/http.sqlite`，按 URL+参数哈希，TTL 默认 30 分钟（避免调试时反复打源；也便于 CI）。
- 每次采集写 `source_runs` 表：`source, started_at, finished_at, status, item_count, error_msg`。
- 健康检查命令：`aipulse doctor` → 逐个 `healthcheck()`，输出 ✅/❌ 表格，并给出修复建议（如"未设置 GITHUB_TOKEN，将受限流至 10 req/min"）。

---

## 6. 归一化与去重（L2）

### 6.1 URL 规范化（canonical_url）

1. 小写 scheme 与 host；去掉默认端口；去掉末尾 `/`
2. 移除追踪参数：`utm_*`、`ref`、`source`、`spm`、`fbclid`、`gclid`、`share_*`
3. 保留有意义参数（如 `?id=`、arxiv id 在 path 中）
4. 对 `arxiv.org/abs/xxx`、`arxiv.org/pdf/xxx`、`huggingface.co/papers/xxx` 做**跨源等价映射** → 统一规范为 `arxiv:{id}`

### 6.2 三级去重

| 级别 | 方法 | 判定 |
|---|---|---|
| L1 精确 | `content_hash = sha1(canonical_url + source)` | 完全相同 → 跳过 |
| L2 跨源 | `cross_source_key`（arxiv_id / repo full_name / HN objectID） | 同 key 合并为一条 Item，`seen_in` 记录多个来源并合并 metrics |
| L3 近似 | `simhash64(title + summary 前 500 字)`，汉明距离 ≤3 | 视为同一事件，合并为 topic 内的同组，保留热度最高者为主条目 |
| L3+（可选，M5） | embedding 余弦 ≥0.92 | 语义相似，不删，只在聚类中归组 |

**合并规则**：保留最早 `published_at`、最新 `metrics`、合并 `tags`、保留 `seen_in: list[source]`。合并后的 Item 热度加成 `+5%`（多源印证 = 更强信号，这个系数可配置）。

---

## 7. 数据模型（SQLite / SQLModel）

### 7.1 items（主表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | uuid4 |
| `source` | TEXT | 主来源 |
| `external_id` | TEXT | 源内 ID |
| `cross_key` | TEXT | 跨源去重键（arxiv:{id} / repo:{full_name}） |
| `title` | TEXT | |
| `url` | TEXT | 规范 URL |
| `summary` | TEXT | 清洗后摘要 |
| `author` | TEXT NULL | |
| `published_at` | DATETIME | UTC |
| `collected_at` | DATETIME | UTC |
| `language` | TEXT NULL | 代码语言或自然语言 |
| `tags` | TEXT | JSON array |
| `metrics` | TEXT | JSON（stars/points/upvotes/...） |
| `seen_in` | TEXT | JSON array，出现过的所有源 |
| `content_hash` | TEXT UNIQUE | |
| `simhash` | TEXT | 64 位指纹 |
| `hot_score` | REAL | 0-100 |
| `topic_id` | TEXT NULL | 聚类结果 |
| `is_duplicate` | BOOL | 被合并的次条目 |
| `dedup_group_id` | TEXT NULL | |
| `raw_ref` | TEXT NULL | 原始快照路径（可选不存） |

索引：`(published_at)`、`(source, published_at)`、`(cross_key)`、`(topic_id)`、`(hot_score DESC)`。

### 7.2 signals（指标时间序列，用于算增速）

| 字段 | 类型 |
|---|---|
| `id` | INTEGER PK AUTOINCREMENT |
| `entity_type` | TEXT（`repo` / `hn_story` / `paper` / `model`） |
| `entity_key` | TEXT（如 `owner/name`） |
| `metric` | TEXT（`stars` / `points` / `comments` / `upvotes`） |
| `value` | REAL |
| `ts` | DATETIME |

唯一索引 `(entity_type, entity_key, metric, ts)`。用途：Δ 值 / 增速 / 趋势曲线。

### 7.3 topics

`id, name, keywords(JSON), representative_item_id, item_count, date, avg_hot_score, summary`

### 7.4 entities（实体频次，趋势推演的原料）

`id, name, type(model/company/framework/concept/person), item_id, date, weight`
用途：统计"本周 vLLM 被提及 37 次，上周 12 次"，驱动周报的趋势判断。

### 7.5 predictions（★ 项目灵魂）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `date` | DATE | 生成日期 |
| `statement` | TEXT | 一句话、可证伪的预言 |
| `category` | TEXT | `capability`/`product`/`research`/`business`/`policy`/`hardware`/`community` |
| `confidence` | REAL | 0.05–0.95，步长 0.05 |
| `horizon_days` | INT | 7 / 30 / 90 / 180 |
| `due_date` | DATE | `date + horizon_days` |
| `falsifiable_criteria` | TEXT | **判定标准**：满足什么算命中、什么算落空 |
| `rationale` | TEXT | 推理链条（3-5 句） |
| `evidence_item_ids` | TEXT | JSON array，引用当日 Item id |
| `model` | TEXT | 生成模型名 |
| `prompt_version` | TEXT | 模板 hash |
| `status` | TEXT | `pending` / `verified` / `unverifiable` |
| `verdict` | TEXT NULL | `hit` / `partial` / `miss` |
| `verdict_score` | REAL NULL | hit=1.0 / partial=0.5 / miss=0.0 |
| `verdict_note` | TEXT NULL | 验证理由 |
| `verdict_evidence_ids` | TEXT NULL | 验证时引用的新 Item id |
| `verified_at` | DATETIME NULL | |
| `verified_by` | TEXT NULL | `auto` / `human` |

### 7.6 运行与成本表

- `source_runs`：`id, source, started_at, finished_at, status, item_count, error`
- `pipeline_runs`：`id, date, stage, status, started_at, finished_at, stats(JSON)`
- `llm_usage`：`id, ts, purpose(brief/predict/verify/debate/trend), model, prompt_tokens, completion_tokens, cost_cny, cache_hit`
- `llm_cache`：`prompt_hash PK, prompt, response, model, created_at`

---

## 8. LLM 抽象层（L3/L4 的桥梁）

### 8.1 接口

```python
class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        response_model: type[BaseModel] | None = None,  # 传入则强制 JSON Schema 约束 + 校验
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",                        # 用于成本归因与预算控制
    ) -> LLMResult: ...   # LLMResult: content: str | BaseModel, usage, cached: bool
```

### 8.2 Provider（v1.1 定为 DeepSeek；**v1.7：移除 openai SDK，改 httpx 直连**）

- **v1.7 决策：不再依赖 `openai` SDK，用项目自带的 `httpx` 直连 `POST {base_url}/chat/completions`。**

  **变更理由（M2 实测暴露的问题）**：
  1. `openai` 3.x 自带 **httpx 2.x**，与项目 `utils/http.py` 依赖的 httpx 版本冲突
  2. **导致 `respx` 无法 mock** —— 而 M3 的预言生成/验证逻辑**强依赖**对 LLM 调用的 mock 测试
     （实测 `openai_compat` 覆盖率因此为 0%）
  3. OpenAI 的 chat/completions 本质就是一个 POST 请求，自研约 60 行即可，**无需重依赖**

  **收益**：消除版本冲突、恢复 mock 能力（M3 必需）、少一个重依赖（对贡献者友好）、
  且项目**已有**重试/缓存/限速/预算全套基建，不需要 SDK 再提供一遍。

  **实现要点**（`llm/openai_compat.py`）：
  ```python
  # POST {base_url}/chat/completions
  # headers: Authorization: Bearer {api_key}, Content-Type: application/json
  # body: {model, messages, temperature, max_tokens, [response_format]}
  # 解析: choices[0].message.content + usage.{prompt_tokens, completion_tokens}
  # 错误处理: 401/403 → ConfigError（不重试）; 429/5xx → 走 HttpClient 退避重试
  ```
  - **必须仍走 `HttpClient`**（复用限速、重试、缓存、代理、UA），不得裸建 httpx 客户端。
  - 错误分类：401/403 → `ConfigError` 立即失败并提示检查 key；429/5xx/超时 → 退避重试；
    其余 4xx → 记录并降级。

- **默认厂商 = DeepSeek**，理由：① 价格低；② 中文表达强；③ 完全兼容 OpenAI 协议，
  未来换厂商**只改环境变量，不改一行代码**。
- 双模型分层（省钱且效果好）：
  - `fast_model = deepseek-chat`：分类、单条点评、证据判定等轻任务
  - `strong_model = deepseek-reasoner`：**预言生成、预言验证、多角色辩论、周期长文**
- 配置示例（`.env`）：
  ```env
  AIPULSE_LLM__PROVIDER=openai_compat
  AIPULSE_LLM__BASE_URL=https://api.deepseek.com/v1
  AIPULSE_LLM__API_KEY=sk-xxx
  AIPULSE_LLM__MODEL=deepseek-chat
  AIPULSE_LLM__FAST_MODEL=deepseek-chat       # 轻任务
  AIPULSE_LLM__STRONG_MODEL=deepseek-reasoner # 预言/验证/辩论/长文
  ```
- 未提供 key 时：`mode` 自动降级为 `off`，注入 `NullLLM`，保证 pipeline 端到端跑通（§8.5）。
- **依赖变更**：从 `pyproject.toml` 移除 `openai`；`uv.lock` 同步更新。
  **M3 开工第一件事就是执行这个移除并补齐 `openai_compat` 的单测**（目标覆盖率 ≥80%）。

### 8.3 结构化输出保障（必须实现）

1. 用 `response_model.model_json_schema()` 生成 JSON Schema，通过 `response_format={"type":"json_schema", ...}` 下发。
   **v1.7：不支持时运行时自动降级**（见下方专项说明）。
2. 拿到响应后 `response_model.model_validate_json()`。
3. 失败 → 触发**一次修复重试**：把错误信息与原输出回传，要求"修正为合法 JSON"。
4. 再失败 → 记录 `llm_usage.error`，该条目降级跳过（绝不中断整条流水线）。

#### 证据 id 的真实验证（v1.11，红线 1 的技术落地）

**真实运行暴露的问题**：当天分析窗口只有 1 条 item，模型却产出 4 条预言、每条 2 个证据 id（共 8 个）。
**1 个真实 id 撑不出 8 个引用——必然有幻觉。** 这直接违反"预言必须基于真实证据"，
且幻觉证据会让整个记分板失去意义（记分板的可信度建立在"每条预言都能追溯到真实条目"之上）。

**必须做两层防护，只做校验是不够的**：

| 层 | 做法 | 为什么 |
|---|---|---|
| **① 预防（先做）** | 把**候选证据池**（id + 标题）显式注入 prompt，明确要求"只能引用此列表中的 id" | 模型有了可引用清单就不容易编。**只做事后校验，会导致证据不足时全被拒收 → 当天一条预言都拿不到** |
| **② 校验（兜底）** | `evidence_item_ids` 必须全部存在于候选池内，否则触发一次重写 → 仍不合法则丢弃并记录 | 防止模型无视清单 |

**★ 候选池的规模约束（v1.16，重要）**：池取 **Top 20，每条只给 `id + 标题`，不给摘要**。

> 窗口修成 24h 后 items 达 174，若池取 30-50 条且带摘要，输入会膨胀约 10 倍：
> ① 涨成本；② 长上下文让模型更容易引用池外 id；③ reasoner 需先输出思维链，
> 输出更长 → 撞 `max_tokens` → 截断 → plain 解析失败 → **生成 0 条**。
> 收窄池同时改善成本、稳定性与幻觉率，**性价比最高**。
> 真需要正文时，验证阶段会重新检索完整证据（单条，不担心长度）。

**★ 关键认识：这个问题的真正根因是分析窗口太窄（见 §18.6）。**
窗口只有 1 条 item 时，无论如何也凑不出 4 条预言 × 2 条证据。
**所以必须先修窗口，证据校验才有意义**——窗口正常后（约 166 条）证据池足够，校验退化为纯兜底。

#### json_schema 运行时自动降级（v1.7）

**背景**：DeepSeek 是否支持 `response_format={"type":"json_schema"}` **无法在无 key 环境下实测**（M2 已确认）。

**决策：采用运行时自动降级，而非让用户手动改配置。**

```
首次请求 → 带 json_schema
   ├─ 成功 → 记住"该模型支持 json_schema"，后续沿用（写入 llm_usage 与内存标记）
   └─ 400 且错误表明不支持该参数 → 自动改用 json_object + prompt 内嵌 schema 重试
        └─ 成功 → 记住"不支持"，后续直接走 json_object（不再每次白试一次）
```

**为什么值得多写这约 20 行**：手动开关（`llm.json_schema: false`）意味着**每个新用户都要先踩一次失败**、
翻文档、改配置才能跑通——这对开源项目的第一印象是致命的。自动降级让用户开箱即用。

**实现要点**：
- 判定"不支持"的依据：HTTP 400 且错误体含 `json_schema` / `response_format` / `unsupported` 等关键词。
- 状态记忆：进程内缓存 + 写入 `llm_usage.error` 便于事后审计；可选持久化到 `llm_cache` 避免每次重启重探。
- 配置仍保留 `llm.json_schema: auto|true|false`（默认 `auto`），供用户强制指定。

#### 三级降级阶梯（v1.12 补全，原来只有两级是断的）

```
① json_schema      → 最强约束
② json_object      → 次强
③ plain（v1.12 新增）→ 不带 response_format，prompt 内嵌 schema，从纯文本解析
```

**为什么必须补第三级**：`deepseek-reasoner`（R1 系列）**两个 structured 参数都不支持**。
缺了第三级，reasoner 场景只能直接 degraded——而第三级是**万能兜底**，
任何模型都支持"输出一段文本"，我们只需能从中解析出 JSON。

解析要健壮：提取 ```json 代码块 → 找不到就取首个 `{` 到末个 `}` → 再失败才算 degrade。

#### 降级状态必须按 `(model, format)` 记忆（v1.12）

**不能用全局布尔。** 支持情况是**按模型**的：`deepseek-chat` 支持 `json_object`，
`deepseek-reasoner` 两者都不支持。全局记忆会让进程先用 reasoner 后，
**chat 也被错误降级**，白白损失结构化输出强度。

#### ★ 模型档位选择是降级的第一道防线（v1.12）

**很多"降级"其实源于用错了档位。** SSOT §8.2 规定 fast 用于轻任务
（分类 / 单条点评 / **主编点评** / 证据判定），strong 仅用于
预言生成 / 预言验证 / 多角色辩论 / 周期长文。

**主编点评此前走 reasoner，同时造成三重损失**：① 拿不到点评；② 更贵；③ 更慢（reasoner 有思维链）。
**遇到降级，先查是不是档位选错了，再看要不要补降级阶梯。**

### 8.4 缓存与预算

- 缓存键：`sha256(model + messages + response_model_name + temperature)`；命中则不计费。
- 预算：`configs/default.yaml` 中 `budget.daily_limit_cny: 2.0`。
- 超限降级顺序（自动）：关闭 `debate` → 关闭 `trend` → 简报只保留 Top 5 → 只做采集不做 LLM。**每次降级必须写日志并体现在报告末尾的"运行元信息"中**。

### 8.5 Prompt 管理

- 全部放 `prompts/**.j2`，由 `llm/prompt.py` 加载并注入变量。
- 每个 prompt 文件头部必须含 YAML front-matter：
  ```yaml
  ---
  version: 1
  model_tier: strong       # fast | strong
  temperature: 0.4
  purpose: predict_generate
  ---
  ```
- `prompt_version` = 该文件的 sha256 前 8 位，入库，便于后续分析"换了 prompt 之后命中率有没有变"。

---

## 9. 分析层（L3，纯算法，零成本）

### 9.1 热度打分 `score.py`

对每个 Item 计算 0-100 的 `hot_score`：

```
engagement_raw =
    github_trending : log1p(stars_in_window) * 1.0 + log1p(stars_total) * 0.2
    hackernews      : log1p(points) + 0.5 * log1p(num_comments)
    reddit          : log1p(score) + 0.5 * log1p(num_comments)
    hf_papers       : log1p(upvotes) * 1.2
    arxiv           : log1p(upvotes or 0) + citation_hint（若无则 0）
    rss / inbox     : 0

engagement_norm = 源内分位归一化到 [0,1]      # 关键：源内归一，避免跨源不可比
freshness       = exp(-max(0, age_hours - 6) / 36)
velocity_norm   = 源内归一化(Δmetric / Δhours)，无历史信号时取源内中位数
source_weight   = configs/sources.yaml 中每个源的静态权重（0-1）
cross_bonus     = 0.05 * (len(seen_in) - 1)

hot_score = 100 * (
    0.45 * engagement_norm
  + 0.20 * freshness
  + 0.20 * velocity_norm
  + 0.15 * source_weight
) + cross_bonus_pts
```

所有权重外置到 `configs/scoring.yaml`，**必须可调参且改动不需改代码**。
`velocity` 依赖 `signals` 表历史，首次运行无历史时该项按源内中位数填充（并在日志提示"冷启动"）。

### 9.2 主题聚类 `cluster.py`

1. 文本 = `title + " " + summary[:500]`；中文用 jieba 分词，英文按空格。
2. `TfidfVectorizer(max_features=20000, stop_words=...)` → 余弦相似度矩阵。
3. 阈值 0.35 建边 → 连通分量 = topic（单点的按 hot_score 单独成组或与最近邻合并）。
4. 每个 topic：取 hot_score 最高者作代表条目，用 TF-IDF top-5 关键词作 `keywords`，`name` 由 LLM 在简报阶段命名（V1 也可直接用 top-3 关键词拼接，省一次调用）。
5. 输出写入 `topics` 表与 `items.topic_id`。

### 9.3 实体抽取 `entities.py`

- V1 用**规则 + 词典**优先（零成本、可解释）：维护 `configs/entities.yaml` 词典（模型名：GPT/Claude/Gemini/Llama/Qwen/DeepSeek/Mistral…；框架：vLLM/PyTorch/Triton/LangChain/Transformers…；公司、硬件：H100/B200/TPU…），正则匹配（含大小写与常见别名）。
- 可选增强（配置开启，M5）：LLM 抽取新实体，人工/自动审核后并入词典。
- 统计每实体每日提及次数 → 支撑周/月趋势的"上升 / 下降 / 涌现"判定。

---

## 10. 推演层（L4，LLM 介入）—— 四大能力

### 10.1 每日简报 + 主编点评（`brief`）

**输入**：当日 Top N（默认 N=30）Item（含 hot_score、topic、metrics、摘要），按 topic 分组。
**输出**（`DailyBrief` Pydantic 模型）：

```python
class ItemComment(BaseModel):
    item_id: str
    one_liner: str          # 一句话说清是什么
    why_it_matters: str     # 为什么重要（因果链，不说套话）
    who_cares: str          # 对谁重要（具体人群/角色）
    what_to_watch: str      # 下一步关注什么（可观测信号）
    novelty: int            # 0-10 新颖度
    impact: int             # 0-10 影响力
    stance: str             # 系统的立场/判断（可以有态度）

class DailyBrief(BaseModel):
    date: date
    headline: str           # 今日一句话头条
    executive_summary: str  # 3-5 句总览
    sections: list[Section] # 板块：开源项目 / 论文与研究 / 社区舆论 / 产业与新闻
    editor_note: str        # ★ 主编点评：今天的整体判断，交叉信号，反直觉观察
    contradictions: list[str]   # 今日信息中的互相矛盾之处
    underrated: list[str]       # 被低估、热度不高但值得关注的条目
    stats: dict
```

**要点**：`editor_note` 与 `contradictions`、`underrated` 是本项目的"人味"所在 —— 纯聚合工具给不了，必须明确要求模型"敢于下判断、指出矛盾、挖掘冷门"。

### 10.2 可回测预言系统（★ 核心差异化）

#### 10.2.1 生成（`predictor.py`）

- 从当日 Top 条目 + 主题演化 + 实体增速中，产出 **3-5 条预言**。
- **强制约束（写进 prompt 并做程序校验）**：
  1. 必须**可证伪**：有明确的 `falsifiable_criteria`（"截至 X 日，若 GitHub 上出现 ≥3 个 star>2k 的开源实现则命中；否则落空"）。
  2. 必须有 `confidence`（0.05-0.95，步长 0.05）——**禁止 0.5 门槛值滥用**，鼓励极端化以便校准度有意义。
  3. `horizon_days` ∈ {7, 30, 90, 180}，每条预言必须落到具体日期。
  4. 必须引用 ≥2 条当日 Item 作为证据（`evidence_item_ids`）。
  5. **禁止**不可证伪表述：出现"可能""也许会变得更""未来值得期待"等模糊措辞 → 程序规则拦截 + 要求重写。
- 覆盖度要求：每批预言尽量覆盖不同 `category`，避免全是"模型能力提升"。

#### 10.2.2 到期验证（`verifier.py`）

- 命令：`aipulse predict verify --due-date 2026-10-11`（每日流水线自动跑）。
- 流程：
  1. 取出 `status=pending AND due_date <= today` 的预言。
  2. 为每个预言检索**证据**：用预言中的实体/关键词在库中检索 **`[生成日, due_date + 3天]`** 窗口内的 Items
     （关键词 + TF-IDF 相似度；M5 后可用 embedding），取 Top 20 条。
     **★ v1.9：窗口左界从"生成日"起算**（而非 `due_date ± 3 天`）。
     理由：预言可能在生成后很早就兑现（如"30 天内会发布"、结果第 5 天就发布了），
     若窗口只覆盖 due_date 附近，这类**已兑现的 hit 会因检索不到证据而被误判成 miss**——
     这会**系统性压低命中率、恶化 Brier**，是必须避免的严重偏差。
  - **模型档位（v1.10）**：验证用 `fast` 还是 `strong` **按运行档位联动** ——
    `hybrid` 档用 `fast`（省钱档就该省到底），`full` 档用 `strong`（追求判定质量）。
    配置项 `verify.model_tier: auto|fast|strong`（默认 `auto` = 跟随档位）。
  - **证据充分度门槛**：证据不足（如少于 3 条过阈值、且无 ≥0.30 强相关单条）→ **不得调用 LLM**，
    直接走 `unverifiable` / 保留 `pending`。既省成本，也避免 LLM 在空白证据上"编造判定"。
  - **`unverifiable` 只能由系统的证据门槛产生，LLM 不得输出该值**（见 §10.2.3 专项说明）。
  3. LLM 按 `falsifiable_criteria` 判定：`hit`(1.0) / `partial`(0.5) / `miss`(0.0) + `verdict_note` + 引用证据 id。
  4. 证据不足 → 标记 `unverifiable`（`status` 字段），并保留 `pending` 最多再延后 7 天（grace period）；
     仍不足则转 `unverifiable`。**LLM 调用失败时保持 `pending`，绝不当 miss 处理。**
  5. 人工 `predict review` 可覆盖 `auto` 判定结果，且**同样计入统计**。
- **人工兜底通道（必须实现）**：
  ```bash
  aipulse predict review <prediction_id> --verdict hit --note "依据：xxx 已于 10-09 发布"
  aipulse predict list --status pending          # 可视化待验证队列
  ```
  理由：纯靠库内检索判定必然有大量"证据不足"，人工一句话即可闭环，且人工判定同样计入统计（记 `verified_by=human`）。

#### 10.2.3 统计与展示（项目的"门面"）

`aipulse stats --predictions` 输出：

- 总数 / 已验证数 / 命中率（hit 比例）/ 加权分（verdict_score 均值）
- **Brier Score**：`mean((confidence - verdict_score)^2)`，越低越好（<0.20 优秀，0.25 为随机猜测基线附近）。
  **★ v1.9：partial 按 `outcome = 0.5` 计入**（与 `verdict_score` 一致），不另设规则
- **校准曲线**：按置信度分桶 **`[0.05,0.5) / 0.5-0.6 / 0.6-0.7 / 0.7-0.8 / 0.8+`**（v1.9 新增低置信桶），
  对比"声称置信度" vs "实际命中率"——**这是最有力的可信度证明**。
  **★ 为什么必须补 `[0.05, 0.5)` 桶**：`confidence` 下限是 0.05，若只统计 0.5+ 的样本，
  所有低置信预言会被静默丢弃——而低置信预言本就该更容易不命中，
  丢掉它们会让校准曲线**系统性偏高失真**，失去作为可信度证明的意义
- **分母口径**：`unverifiable` 与 `pending` **不计入分母**——它们没有判定结果，计入会稀释统计意义
- 按 `category` / `horizon_days` / `model` / `prompt_version` 分组的命中率
- 自动生成"预言记分板" Markdown/HTML，作为 README 与 Web 首页的核心展示模块

> 展示建议：README 顶部直接放一张「预言记分板」表格 + 校准曲线图。这在开源社区极具传播力，也是本项目最有辨识度的资产。

#### `unverifiable` 的归属与防滥用（v1.9 明确）

| 项 | 规定 |
|---|---|
| 归属 | **`status` 字段**，不是 `verdict`。`Verdict` 保持 3 值契约（`hit` / `partial` / `miss`）不变 |
| 产生方 | **只允许系统的证据门槛产生**，LLM **不得**输出 `unverifiable` |
| 理由 | 若允许 LLM 输出，它会变成**逃避 miss 的软出口**——模型一旦犹豫就标"无法验证"，<br>命中率与 Brier 都会被系统性美化，整个记分板失去意义 |
| 部分命中 | `partial` 必须**高度克制**：仅当①存在可列举的多个子条件且部分满足，或②量化阈值落在容差带（默认 5%）时使用。<br>**"拿不准" ≠ partial**——拿不准应走证据门槛 → `unverifiable` 或延后重试 |
| miss 的前提 | **证据覆盖已充分**。"查不到"不等于"没发生"，不得因检索不到就判 miss |

### 10.3 周期趋势长文（`trend`）

- 命令：`aipulse trend --range 7d|30d`
- 输入：本期 topics 演化、实体频次 Top-N 及其环比变化、signals 增速 Top-N、本期简报与预言的聚合、往期预言验证结果。
- 输出（`TrendReport`）：
  - `executive_summary`
  - `rising_topics` / `declining_topics` / `emergent_topics`（各 3-5 个，带数据支撑）
  - `structural_changes`（结构性变化，如"推理成本曲线的二阶效应"）
  - `second_order_effects`（二阶/三阶推演，明确标注为推测）
  - `predictions_review`（往期预言复盘）
  - `next_period_watchlist`（下期观察清单，与预言系统联动）
  - 正文 2000-4000 字，Markdown，带数据表格

### 10.4 多角色辩论（`debate`）

- 命令：`aipulse debate --topic "开源模型能否在 12 个月内追平闭源前沿" [--rounds 2]`
- 角色（4 个 persona，prompt 外置）：
  1. **乐观派（Bull）**：技术加速、能力跃迁
  2. **怀疑派（Bear）**：数据/算力/评测泡沫、历史类比
  3. **工程派（Engineer）**：落地成本、延迟、可维护性、真实收益
  4. **投资/商业派（Investor）**：单位经济、护城河、市场结构
- 流程：
  - Round 1：四个 persona 并行（asyncio.gather）各自陈述（输入为同一份压缩后的证据包：相关 Items Top 15 + 统计数据）
  - Round 2：把四份陈述汇总后，各自做一轮反驳/修订（可选，`--rounds 2`）
  - 主持人收敛：输出 `consensus`、`key_disagreements`、`actionable_conclusions`、`overall_confidence`、以及**"什么证据会让我改变判断"**
- 成本控制：4 persona × 2 轮 + 主持人 = 最多 9 次调用；默认 `--rounds 1`（5 次）。辩论结果入库并存为报告文件，可被周报引用。
- **辩论触发**：可配置为每周自动就"本周最大争议话题"发起一次辩论（话题由 LLM 从本周数据中选出）。

---

## 11. 输出与渲染（L5）

每次运行产出到 `data/reports/YYYY/MM/DD/`：

| 文件 | 内容 |
|---|---|
| `brief.md` | 每日简报（主产物，人读） |
| `brief.html` | HTML 版（可选，带基础样式，便于分享） |
| `predictions.md` | 当日新生成的预言 |
| `verdicts.md` | 当日到期的验证结果 |
| `scoreboard.md` | **★ 预言记分板（v1.10：`daily` 流水线自动产出）** |
| `debate-<slug>.md` | 辩论记录（若有） |
| `daily.json` | 全量结构化结果（机器读，供 Web/二次开发） |
| `meta.json` | 运行元信息：耗时、各源条数、LLM 调用次数/花费、降级情况 |

**记分板产出时机（v1.10）**：`daily` 流水线在 `auto_verify` 之后**自动**生成
`data/reports/YYYY/MM/DD/scoreboard.md`（这样 Actions 每天 commit 的报告中天然包含记分板）。
`aipulse stats --predictions` 命令本身**默认只打印，不落盘**，需 `--out <path>` 显式指定才写文件——
查询类命令默认不产生副作用，符合 CLI 直觉。

**报告模板原则**：
- Markdown 顶部有元信息块（生成时间、模型、数据源统计、花费）
- 每条条目：**标题 + 链接 + 来源徽章 + 热度分 + 一句话 + 点评**
- 预言部分必须包含置信度与验证日期，可点击追溯
- 末尾固定附「本次运行元信息」与「数据声明（来源与合规说明）」

**Web UI（M4，可选）**：FastAPI + Jinja2 + HTMX，只读页面：
`/`（今日简报）、`/archive`（按日期浏览）、`/predictions`（预言记分板 + 校准曲线）、`/topics`（主题演化）、`/search`（关键词检索）。数据全部来自 SQLite 与 `daily.json`，**不做任何写操作**。

### 11.2 日报触达与通知抽象（v1.2 确认）

**当前决策：以「文件 + Web 看板」为主，不做额外推送。** 但**架构上必须预留统一的 Notifier 抽象**，后续加邮件/Telegram/飞书时不需要改 pipeline。

```python
# src/aipulse/notify/base.py
class Notifier(Protocol):
    name: str                                   # "file" | "email" | "telegram" | "feishu"
    async def send(self, report: RenderedReport) -> NotifyResult: ...
```

- **M4 只实现 `FileNotifier`**（写 `data/reports/`），它是当前唯一的默认实现。
- `configs/default.yaml` 中 `notify.channels: [file]`，后续加渠道只需追加名字并实现对应类——**pipeline 代码零改动**。
- 预留渠道及实现要点（**现在不要实现**，仅登记，避免提前付成本）：

| 渠道 | 实现要点 | 何时值得加 |
|---|---|---|
| 邮件（SMTP） | Actions 内用 QQ/163 免费 SMTP，把 `brief.md` 正文发出 | 如果你发现自己连续几天忘了打开看板 |
| Telegram Bot | 需 bot token；国内需代理 | 想要手机推送且能解决网络 |
| 飞书/企微机器人 | 需建企业应用，webhook 相对简单 | 有团队协作需求时 |
| Windows 桌面通知 | 仅本地 cron 场景有效，Actions 场景无意义 | 基本不推荐，WSL→Windows 通知桥较折腾 |

- **判断标准**：先用文件 + 看板跑两周。若确实出现"产出没人看"的情况，再花半小时加邮件推送——**这是最容易补的一环，不值得提前设计**。


### 11.4 手写预言（v1.3：提升为全档位核心能力）

**这是无 API 档位仍能拥有预言系统的关键，也是本项目区别于同类工具的重要设计。**

核心认知：**预言的价值在于「被追踪、被验证、被统计」，而不在于「由谁生成」。**
一条人写的、有明确判据的预言，与模型生成的预言在记分板上完全同权——都进入命中率统计、都参与 Brier Score 与校准曲线。
有 API 时还能**对比人与机器的校准度**（`predictions.origin` 字段区分 `human` / `llm`），这本身就是很有传播价值的数据。

#### 11.4.1 交互方式（v1.3 权衡结论：参数 + 交互式向导自动降级）

```bash
# 方式 A：全参数一次到位（适合脚本、Actions、熟练用户）
aipulse predict add "Qwen3-Next 将在 30 天内发布" \
  --confidence 0.75 \
  --due 2026-11-10 \
  --criteria github_new_repo --param owner=Qwen \
  --note "通义实验室近期密集预热"

# 方式 B：不带参数则自动进入交互式向导（适合日常随手记录）
aipulse predict add
```

**向导流程**（`typer.prompt` + `rich` 实现，无需额外依赖）：

```
? 预言内容（一句话，要可证伪）: Qwen3-Next 将在 30 天内发布
? 置信度 (0.05-0.95，步长0.05) [0.6]: 0.75
? 到期天数 [30]:
  ❯ 7 天   30 天   90 天   180 天   自定义
? 判据类型（决定到期如何自动验证）:
  ❯ 1. GitHub 某账号出现新仓库
    2. 某仓库 star 数达到阈值
    3. HN 上某关键词故事达到 X 分
    4. 某实体在库中提及次数达到阈值
    5. arXiv 某关键词论文数达到阈值
    6. 暂不设定（到期人工判定）
? 目标 owner/账号: Qwen
? 备注/推理依据（可选）: 通义实验室近期密集预热

── 预览 ────────────────────────────────
  内容: Qwen3-Next 将在 30 天内发布
  置信度: 0.75   到期: 2026-11-10 (30天)
  判据: github_new_repo(owner=Qwen) >= 1
  依据: 通义实验室近期密集预热
────────────────────────────────────────
? 确认写入? [Y/n]:
✅ 已写入，id=pred_7f3a2c，到期日 2026-11-10
```

#### 11.4.2 为什么值得为向导多写这几十行（开发量权衡）

| 方案 | 代码量 | 体验 | 问题 |
|---|---|---|---|
| 纯参数 | ~60 行 | 差 | **手写 JSON 判据极其痛苦**，用户会因麻烦而放弃使用，off 档等于失去预言能力 |
| 纯向导 | ~130 行 | 好 | 无法在脚本/Actions 中使用 |
| **参数 + 缺参自动降级为向导** | **~100 行** | **最好** | 无 |

**权衡结论：采用第三种。** 关键洞察——它不是两套独立代码，而是**同一套参数定义**，
仅把必填参数设为 `Optional`，为 `None` 时用 `typer.prompt()` 追问。
因此相比纯参数方案**只多约 40 行**（追问逻辑 + 判据模板选择 + 预览确认），却同时获得了向导的好体验和脚本可用性。

> 判据模板列表（§11.5）是向导体验的核心：把"手写 JSON"变成"选模板 + 填字段"，
> 这也是**让量化判据真正被用起来**的关键——否则绝大多数人会跳过这个字段。

#### 11.4.3 实现要点

- 所有参数声明为 `Optional[...]`，`None` 时触发 `typer.prompt()`；`--yes` 可跳过确认预览（脚本用）。
- 判据选择用 `rich.prompt.Prompt.ask(choices=[...])`，序号选择。
- 向导末尾必须渲染**预览卡片**并二次确认——预言一旦入库就参与统计，不能误写。
- 生成的预言 `origin = "human"`，与模型预言 `origin = "llm"` 在记分板上可分组对比。

### 11.4.4 向导的字段收集策略（v1.8 明确）

| 字段 | 是否收集 | 说明 |
|---|---|---|
| `statement` | ✅ 必填，第一步 | |
| `confidence` | ✅ 必填（有默认 0.6，回车即可） | |
| `horizon_days` | ✅ 必填（7/30/90/180 序号选择） | |
| `criteria`（量化判据） | ⚠️ **可选** | 选模板 → 自动渲染 `falsifiable_criteria` |
| **`falsifiable_criteria`（判据文本）** | ✅ **必填（红线）** | 选了模板 → 自动填充；**选"不设定" → 向导必须追问一句话判据**，不得留空 |
| **`category`** | ✅ 收集（v1.8 新增，有默认值） | 7 个序号选项，默认 `capability`，回车跳过 |
| `rationale` | ⚠️ 可选 | `--note` 或向导末尾可选填写 |

**为什么 `category` 必须收集**（v1.8 决策）：
M3b 要做「按 `category` 分组的命中率统计」（§10.2.3）。若手写预言全部默认 `capability`，
这个分组维度就只剩单一取值，**统计完全失去意义**。收集成本极低（一步序号选择 + 回车默认），
收益是保住一个分析维度。

### 11.5 量化判据（v1.3 新增，可选字段）

预言可附带一个**可机读的判据**，到期时**直接查库判定，零 API 成本**。

```json
{
  "criteria": "github_stars_reach",
  "params": {"repo": "vllm-project/vllm", "threshold": 80000}
}
```

**内置判据模板库**（`configs/criteria.yaml`，可扩展）：

| 模板名 | 含义 | 参数 | 判定方式 |
|---|---|---|---|
| `github_new_repo` | 某 owner 出现新仓库 | `owner` | 查 `signals` 中该 owner 的 repo 集合是否新增 |
| `github_stars_reach` | 某仓库 star 达到阈值 | `repo`, `threshold` | 查 `signals(entity=repo, metric=stars)` 最新值 |
| `hn_story_points` | HN 上某关键词故事达 X 分 | `keyword`, `threshold` | 检索 `items` 中 `source=hackernews` 且标题含关键词 |
| `entity_mentions` | 某实体在库中提及数达阈值 | `entity`, `threshold`, `window_days` | 统计 `entities` 表 |
| `arxiv_paper_count` | arXiv 某关键词论文数达阈值 | `keyword`, `threshold`, `window_days` | 统计 `items` 中 `source=arxiv` |
| `custom` | 手写表达式 | `expr` | 兜底，供高级用户。**当前支持 5 原语 + `and`/`or`/`not`** |
| *（不设定）* | 到期人工判定 | — | off/hybrid 档人工 `predict review`；full 档走 LLM |

**三重收益**：
1. **省钱**——量化判据不走 LLM，off 档也能自动验证
2. **快**——查表即判，无需检索与推理
3. **倒逼预言质量**——填判据的过程会强迫你把预言写清楚，"大模型会变得更聪明"这类模糊句根本填不出判据

**不强制**：允许不设判据（走人工或 LLM 判定），因为有些预言本质是语义判断，强行量化会损失有意义的预言。

**关于 `custom` 的覆盖面（v1.10 裁定）**：当前支持 5 原语 + `and`/`or`/`not`。
**暂不扩展比较与算术运算符**——6 个内置模板已覆盖绝大多数场景，
`custom` 定位是"高级用户兜底"而非常规路径。若后续真实使用中确实遇到表达不了的需求，再按需扩展（YAGNI）。

---

## 12. CLI 设计

```bash
# 初始化与环境
aipulse init                       # 建库、生成配置骨架、创建目录
aipulse doctor                     # 检查依赖/API key/各源连通性/磁盘/时区

# 采集与处理
aipulse collect [--sources github_trending,arxiv] [--since 24h] [--dry-run] [--no-cache]
aipulse normalize                  # 可单独跑（调试用）
aipulse analyze --date today       # 打分 + 聚类 + 实体统计

# 推演与产出
aipulse brief  --date today [--top-n 30] [--format md|html|json]
aipulse predict --date today [--max 5] [--horizons 7,30,90]      # 自动生成（hybrid/full 档）
aipulse predict add ["内容"] [--confidence 0.75] [--due 30d] [--criteria X] [--note "..."] [--yes]
                                            # 手写预言：不带参数则进入交互式向导（v1.3，全档位可用）
aipulse predict list [--status pending|verified] [--origin human|llm]
aipulse predict verify [--due-date today]   # 量化判据自动判定；其余按档位走人工或 LLM
aipulse predict review <id> --verdict hit|partial|miss --note "..." 
aipulse debate --topic "..." [--rounds 1|2]
aipulse trend --range 7d|30d

# 一条龙
aipulse daily [--date today] [--skip-llm]   # collect→normalize→analyze→brief→predict→verify→render

# 查询与运维
aipulse stats [--predictions] [--days 30]
aipulse topics --date today [--top 10]
aipulse search "vLLM" [--days 7]
aipulse inbox add <url> [--note "..."]
aipulse sources list|enable|disable
aipulse serve [--port 8000]        # M4

# 通用选项
--config <path>   -v/--verbose   --json（结构化输出，便于脚本消费）   --no-llm（纯算法模式）
```

- 交互输出用 `rich`：进度条、表格、彩色状态；`--json` 时全部转为结构化输出（便于管道与自动化）。
- 所有命令必须支持 `--dry-run`（不写库、不调 LLM，只打印将要做什么）。

---

## 13. 配置系统

### 13.1 `configs/default.yaml`（示意）

```yaml
app:
  name: aipulse
  timezone: Asia/Shanghai          # 存储统一 UTC，展示用此
  data_dir: data
  log_level: INFO

# ★ v1.3：运行模式。off=零 API 花费；hybrid=仅预言+点评；full=全部
#   未配置 api_key 时自动降级为 off，不报错退出
mode: full

llm:
  enabled: true                    # mode 为 off 时强制 false
  provider: openai_compat
  base_url: ${AIPULSE_LLM__BASE_URL}
  api_key: ${AIPULSE_LLM__API_KEY}
  fast_model: deepseek-chat
  strong_model: deepseek-reasoner
  temperature: 0.4
  timeout_s: 120
  max_retries: 3
  cache_enabled: true

budget:
  daily_limit_cny: 2.0
  degrade_order: [debate, trend, brief_topn, all]

pipeline:
  daily_top_n: 30
  brief_sections: [开源项目, 论文与研究, 社区舆论, 产业与新闻]
  predictions_per_day: 5
  prediction_horizons: [7, 30, 90]
  auto_verify: true
  weekly_debate_enabled: true

output:
  formats: [md, json]
  html_enabled: true
  dir: data/reports

notify:
  channels: [file]        # v1.2 只有 file；预留 email/telegram/feishu/desktop（暂不实现）
  # email: { smtp_host: , smtp_port: 465, user: , to: }   # 预留，不要实现

http:
  timeout_connect_s: 5
  timeout_read_s: 20
  max_concurrency: 6
  cache_ttl_s: 1800
  user_agent: "aipulse/0.1 (+https://github.com/<you>/aipulse)"
```

### 13.2 `configs/sources.yaml`（示意）

```yaml
sources:
  github_trending:
    enabled: true
    weight: 1.0
    rate_limit: "1/6h"
    windows: [daily, weekly]
    languages: [python, typescript, ""]
    fallback_search_api: true
    track_signals: true            # 写 signals 表算增速
  arxiv:
    enabled: true
    weight: 0.8
    rate_limit: "3/s"              # 硬限制
    categories: [cs.AI, cs.LG, cs.CL, cs.CV, cs.MA, stat.ML]
    max_results: 200
    keyword_filter: [llm, agent, multimodal, diffusion, inference, rl, reasoning]
    top_n_after_filter: 60
  hf_papers:
    enabled: true
    weight: 0.9
    rate_limit: "1/1s"
    enrich_repos: true             # 调 /api/arxiv/{id}/repos
  hackernews:
    enabled: true
    weight: 0.85
    rate_limit: "10/1s"
    queries: [AI, LLM, GPT, Claude, "open source model", agent, inference]
    min_points: 30
    window_hours: 48
    with_comments_top: 3
  reddit:
    enabled: true
    weight: 0.55                   # v1.2：RSS 模式无 score，降权
    mode: rss                      # rss（默认，免认证）| oauth（需 client_id/secret）
    subreddits: [LocalLLaMA, MachineLearning]
    # RSS 模式无 score，用 (N-rank)/N 排名位次作热度代理；M1 验收后再评估是否升级 OAuth
  rss:
    enabled: true
    weight: 0.6
    feeds:
      # ── 英文主干（稳定、信噪比高，新闻板块基本盘）────────────────
      - {name: Simon Willison,  url: "https://simonwillison.net/atom/everything/", tier: core}
      - {name: Import AI,       url: "https://importai.substack.com/feed",          tier: core}
      - {name: Latent Space,    url: "https://www.latent.space/feed",               tier: core}
      - {name: Anthropic Blog,  url: "https://www.anthropic.com/rss.xml",           tier: core}
      - {name: OpenAI Blog,     url: "https://openai.com/blog/rss.xml",             tier: core}
      - {name: HF Blog,         url: "https://huggingface.co/blog/feed.xml",        tier: core}
      - {name: The Verge AI,    url: "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", tier: core}
      - {name: TechCrunch AI,   url: "https://techcrunch.com/category/artificial-intelligence/feed/",     tier: core}
      - {name: Ars Technica AI, url: "https://arstechnica.com/ai/feed/",            tier: core}
      # ── 中文补充（optional：失效只告警不报错，不阻塞流水线）────────
      - {name: 机器之心, url: "https://www.jiqizhixin.com/rss", tier: optional}
      - {name: 量子位,   url: "https://www.qbitai.com/feed",    tier: optional}
      # ⚠️ 上述所有 URL 必须在 M0 用 scripts/probe_sources.py 逐个实测：
      #    记录 HTTP 状态 / 条数 / 是否含正文 / 最后更新时间，失效的当场替换或删除。
      #    结论写入 docs/数据源手册.md。禁止把未经验证的 URL 留在生产配置里。
  inbox:
    enabled: true
    weight: 0.5
```

> **关于中文源的 `optional` 标记**：`optional: true` 的源在探测失败、返回空、或解析异常时，
> **只写 warning 日志并在 `source_runs` 中标记 `degraded`**，绝不影响 pipeline 退出码。
> 这是 v1.2「英文主干 + 中文补充」策略的工程落地——中文源挂了不影响当天出报告。

### 13.3 环境变量（`.env.example`）

```env
# ★ 不填也能用：未配置时自动按 off 档运行（见 §8.5）
AIPULSE_LLM__API_KEY=
AIPULSE_LLM__BASE_URL=
GITHUB_TOKEN=            # 可选，强烈建议
HF_TOKEN=                # 可选，提高 HF 限额
REDDIT_CLIENT_ID=        # 仅 oauth 模式需要
REDDIT_CLIENT_SECRET=
HTTP_PROXY=              # WSL 环境可能需要
HTTPS_PROXY=
```

---

## 14. 调度与自动化

### 14.1 GitHub Actions（主）

```yaml
# .github/workflows/daily.yml
on:
  schedule: [{ cron: "0 23 * * *" }]   # UTC 23:00 = 北京 07:00
  workflow_dispatch:
jobs:
  daily:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run aipulse daily --date today
        env: { AIPULSE_LLM__API_KEY: ${{ secrets.LLM_API_KEY }}, GITHUB_TOKEN: ${{ secrets.GH_TOKEN }} }
      - name: Commit reports
        run: |
          git config user.name "aipulse-bot"
          git add data/reports
          git diff --staged --quiet || git commit -m "chore(reports): $(date +%F)"
          git push
```
> 注意：Actions 环境无法持久化 SQLite（每次全新）。**解决**：① 报告与预言以文件形式 commit 回仓库（文本即数据库）；② 或用 Actions cache 保存 `data/aipulse.db`（key 用日期，restore-keys 兜底）；③ 或把 `signals` 增速计算做成"从 GitHub API 现取 + 上一次报告里的快照"。**V1 推荐 ①+②组合**：SQLite 走 cache 尽力而为，报告文件commit 保证可追溯。

### 14.2 仓库公开策略（v1.2 确认：M0 即公开）

**决策：M0 建仓时就设为 public，边开发边公开。**

理由：
- **开发过程本身就是说服力**：一个能看到完整 git 历史、每阶段有验收记录、README 里写着真实取舍理由的仓库，比一个突然出现的"成品"更可信。对面试与开源传播而言，过程比结果更有信息量。
- **早期反馈**：M0 阶段的数据源探测结果，很可能有人愿意告诉你"某某源还有更好的端点"。
- **丢掉的心理负担**：不必等"完美"再公开——本项目本来就是持续运行的系统，永远没有"完成态"。

落地要求（M0 必须做）：
1. README 顶部放状态徽章与 WIP 声明：
   ```markdown
   > 🚧 **WIP / 开发中**：当前已完成 M0（骨架与数据源探测），正在推进 M1（采集器）。
   > 功能尚不完整，但每日报告会持续产出——见 [`data/reports/`](data/reports/)。
   ```
2. README 必须包含 **Roadmap 勾选清单**（M0-M5 每个阶段打勾状态），让人一眼看出进度。
3. `.github/workflows/ci.yml` 从 M0 就配上，让仓库徽章从第一天起就是绿的。
4. 每阶段验收后更新 README 的进度勾选，并在 `docs/开发日志.md` 追加记录。
5. **密钥零入库**：`.gitignore` 含 `.env`、`data/*.db`、`data/cache/`；M0 第一次 push 前用 `git-secrets` 或人工检查一遍。

> 注意：`data/reports/` 是要**公开 commit** 的（这是 Actions 持久化的手段之一），
> 但 `data/aipulse.db` 与 `data/cache/` 必须 gitignore。确保二者不会混淆。

### 14.3 本地常驻（备）

WSL 内 `crontab -e`：
```
0 7 * * * cd ~/projects/aipulse && .venv/bin/aipulse daily >> logs/cron.log 2>&1
```
Windows 侧也可用"任务计划程序"调用 `wsl -e bash -lc "..."`（需开启 WSL 后台运行）。

---

## 15. 开发环境（WSL2 专项注意事项）

| 事项 | 要求 |
|---|---|
| 代码位置 | **必须放 WSL 原生 ext4 文件系统**（如 `~/projects/aipulse`），**禁止放 `/mnt/c/`**（跨文件系统 I/O 极慢、SQLite 文件锁与 git 行为异常） |
| 编辑器 | VSCode 安装 **Remote - WSL** 扩展，从 WSL 内 `code .` 打开 |
| Python | WSL 内 `uv python install 3.11` + `uv venv`，**不要**用 Windows 侧 Python |
| 网络 | 若需代理，配置 `HTTP_PROXY`/`HTTPS_PROXY` 并在 `HttpClient` 中显式支持；`aipulse doctor` 应能检测并提示代理问题 |
| 换行符 | 仓库内 `git config core.autocrlf input`，统一 LF；`.gitattributes` 固化 |
| 时区 | 全部时间 UTC 入库，展示按 `Asia/Shanghai`；WSL 时钟与 Windows 可能漂移，用 `sudo hwclock -s` 或在 doctor 中校验 |
| 中文字体 | 终端与 HTML 报告用系统已装字体；Linux 下如需渲染图表用 `WenQuanYi Micro Hei` |
| 数据库 | `data/aipulse.db` 加入 `.gitignore`；提供 `scripts/export_site.py` 导出可公开的数据 |
| 文件监听 | WSL 下 inotify 正常，Web 开发可用 `--reload` |

---

## 16. 分阶段里程碑（Agent 必须按此顺序执行）

每个里程碑包含：任务清单 + **验收标准（DoD）**，DoD 未全部满足不得进入下一阶段。

### 16.0 为什么 v1.1 把「发布与自动化」提到「深度推演」之前

原方案顺序是 M4（周期长文 + 多角色辩论）→ M5（Web + Actions + README）。**v1.1 对调为：M4（发布与自动化）→ M5（深度推演）。**

**核心理由：预言记分板的价值只能靠时间沉淀，而这段时间是任何技术手段都压缩不掉的。**

- 预言系统（M3）建好当天，库里是 **0 条已验证预言**——这时候的记分板是空的，README 上什么都放不出来。
- 只有让系统**每天自动跑**（Actions 定时 + 报告 commit），预言才会逐日到期、逐日被验证。跑满 30 天 ≈ 150 条预言、其中 7 日期限的约 100 条已验证；跑满 90 天才有完整的分桶校准曲线（尤其是 90/180 天 horizon 的样本）。
- 也就是说，`aipulse` 最有说服力的资产——**"我声称 80% 把握的预言，实际命中率是 79%"**——需要真实运行一个月才开始有意义。越早开始跑，这份成绩单越早值钱。
- 反观周期长文与多角色辩论：它们是**内容质量的加分项**，任何时候做都能立刻见效，不存在"等待期"。晚做一个月，损失为零。

结论：**先把数据流水打开跑起来（M4），让时间在替你积累资产；再利用这段时间从容做深度能力（M5）。**

> 顺序影响到的引用：web/ 目录与 `aipulse serve` 属 M4；`trend` / `debate` / `pipeline/weekly.py` / 可选 embedding 属 M5；Web 首页的"辩论"与"趋势"入口在 M4 先留占位，M5 完成后点亮。

### M0 · 骨架与数据探测（预计 0.5-1 天）
1. `uv init` 建项目，配置 `pyproject.toml`（含 ruff/mypy/pytest）、pre-commit、目录骨架（按 §4 建空包）。
2. 实现 `core/config.py`、`core/logging.py`、`core/timeutil.py`、`core/hashing.py`、`utils/http.py`。
3. 实现 `schema/items.py`、`store/models.py`（全表）、`store/db.py` + alembic 初始化。
4. **写 `scripts/probe_sources.py`**：对每个源发一次真实请求，打印字段样例，并把原始响应存到 `tests/fixtures/`。
5. 写 `docs/数据源手册.md`：记录每个源的真实字段、限速、失效时的降级路径。
6. CLI 骨架：`aipulse --help`、`init`、`doctor`。

**DoD**：
- [ ] `uv run aipulse --help` 正常，所有子命令可见
- [ ] `uv run aipulse doctor` 能检测 Python 版本/LLM key 是否配置/各源连通性（探针版）
- [ ] `tests/fixtures/` 下有 **全部 6 个源**的真实响应快照
- [ ] 数据库所有表可创建，`pytest` 通过基础测试
- [ ] **《数据源手册》完成，且报告中明确写出哪些源探测失败及原因**

### M1 · 采集器全量实现（1-2 天）
1. 实现 6 个采集器 + `registry.py`，每个都有解析单测（基于 fixtures，零网络）。
2. `HttpClient` 完善：限速（令牌桶）、重试、缓存、UA、代理。
3. `normalize/clean.py` + `normalize/dedup.py` 三级去重。
4. `collect` 命令：`--sources` / `--since` / `--dry-run` / `--no-cache`；并发编排；`source_runs` 记录。
5. 单源失败隔离：注入故障测试（mock 成 500/超时）验证 pipeline 不崩。

**DoD**：
- [ ] `aipulse collect --since 24h` 在真实网络下能采到 ≥4 个源的数据，总数 ≥50 条
- [ ] 断网/单源失败时其余源照常完成，退出码与日志正确
- [ ] 每个采集器单测覆盖率 ≥80%；`pytest` 全程无需网络
- [ ] 去重生效：arXiv 与 HF Daily Papers 的同一篇论文合并为 1 条
- [ ] GitHub repo 的 stars 快照正确写入 `signals`

### M2 · 分析层 + 每日简报（1-2 天）
1. `analysis/score.py`（权重外置）、`cluster.py`（TF-IDF）、`entities.py`（词典+规则）、`signals.py`。
2. `llm/`：base / openai_compat / structured / cache / budget / prompt；`FakeLLM`。
3. `reasoning/brief.py` + `prompts/brief/*.j2`；`render/markdown.py` / `json_out.py`。
4. `aipulse analyze`、`aipulse brief`、`aipulse daily` 打通。

**DoD**：
- [ ] `aipulse daily --skip-llm` 端到端跑通并产出 `daily.json`（零 API 花费）
- [ ] `aipulse brief` 产出的 `brief.md` 结构完整、含主编点评与"被低估"板块
- [ ] 改 `configs/scoring.yaml` 权重无需改代码即生效（有单测验证）
- [ ] LLM 输出非法 JSON 时自动修复重试，二次失败降级跳过且不中断（有单测）
- [ ] 预算超限自动降级，并在 `meta.json` 中体现

### 16.1 M3 拆分为 M3a / M3b（v1.7）

**M3 是项目灵魂，也是最大的一个里程碑，拆成两个子阶段执行。**

| 子阶段 | 内容 | 交付物 | 会话策略 |
|---|---|---|---|
| **M3a · 生成** | 预言生成、入库、不可证伪拦截、手写预言 `predict add`（含交互式向导）、量化判据模板库 | `predict` 命令可用，预言能入库 | 独立会话（S/A 档模型） |
| **M3b · 验证与统计** | 到期验证、证据检索、量化判据自动判定、人工 review、命中率/Brier/校准曲线、记分板 | 记分板可生成，闭环成立 | 独立会话（A 档模型） |

**拆分理由**：
1. **单次会话负担过重** —— 生成 + 验证 + 统计 + 记分板一次做完，上下文里塞太多东西，质量难保证
2. **生成逻辑需要单独验收** —— 如果生成有问题（比如拦截规则太松导致预言含糊），
   等验证和统计都做完才发现，返工成本大得多
3. **每个子阶段上下文干净** —— 符合 §6.5 的会话管理原则

> **注意**：M3a 完成后预言**还不能闭环**（没有验证与统计），这是预期状态，不是缺陷。

### M3 · 预言系统（★ 最关键，1-2 天）
1. `reasoning/predictor.py` + `prompts/predict/generate.j2`；`schema/prediction.py`。
2. 不可证伪措辞拦截规则（正则黑名单 + 二次生成）。
3. `reasoning/verifier.py` + `prompts/predict/verify.j2`；证据检索；自动验证。
4. `aipulse predict` 全套子命令 + 人工 review 通道。
5. `aipulse stats --predictions`：命中率、加权分、**Brier Score**、校准曲线（Markdown 表格 + 可选 ASCII/PNG 图）。

**DoD**：
- [ ] 生成的每条预言都有 `confidence`、`due_date`、`falsifiable_criteria`、≥2 条证据
- [ ] 校验器能拦截"可能/也许"类模糊预言并触发重写（单测覆盖）
- [ ] 人工 `predict review` 能闭环，且计入统计
- [ ] `aipulse stats --predictions` 输出命中率 + Brier + 分桶校准表
- [ ] **预言记分板 Markdown 可自动生成，能直接贴进 README**

### M4 · Web 看板 + 自动化 + 开源发布（1-2 天）  ← 原 M5，v1.1 提前

> **本阶段最重要的产物不是代码，而是"系统开始每天自动跑了"。** 从这一天起，预言数据开始逐日积累。

1. **GitHub Actions 优先做**（本阶段第一优先级，做完立刻让它跑起来）：
   - `daily.yml`：cron `0 23 * * *`（UTC 23:00 = 北京 07:00）+ `workflow_dispatch`
   - `ci.yml`：ruff + mypy + pytest，**必须能在无密钥环境全绿**
   - Actions 无持久化问题的三条对策：报告文件 commit + `actions/cache` 恢复 `data/aipulse.db` + 关键 `signals` 落 `signals.json`
   - 另配 WSL 本地 cron 作为备份（见 §14.3）
2. `web/app.py`（FastAPI + Jinja2 + HTMX，只读）：`/`（今日简报）、`/archive`（按日期）、`/predictions`（**预言记分板 + 校准曲线**）、`/topics`、`/search`。
   - 「辩论」与「趋势」入口本阶段先置灰占位，M5 完成后点亮。
   - `aipulse serve --port 8000`；禁止任何写操作。
3. README 重写：一句话定位、能力清单、5 分钟快速开始（`init → doctor → daily`）、截图/示例、**预言记分板（自动生成贴入）**、架构图（mermaid）、数据源与合规声明、Roadmap（明确标注 M5 待做）、贡献指南。
4. LICENSE（**MIT**）、CONTRIBUTING.md、`.github/ISSUE_TEMPLATE`、`.gitattributes`（统一 LF）。

**DoD**：
- [ ] **Actions 定时跑通并 commit 报告**（至少用 `workflow_dispatch` 手动验证一次真实运行）
- [ ] Actions 内 SQLite 恢复机制生效：连续两天运行后，`signals` 能算出 star 增速（有数据佐证）
- [ ] `aipulse serve` 本地可浏览，页面包含预言记分板与校准曲线
- [ ] `ci.yml` 在无密钥环境下 lint + mypy + test 全绿
- [ ] README 可被陌生人 5 分钟内跑通；记分板已贴入（即使此刻样本数为 0，也要展示结构）

### M5 · 周期长文 + 多角色辩论（1-2 天）  ← 原 M4，v1.1 后移

> 此时系统已自动运行一段时间，库里有真实的历史数据与已验证预言可供长文与辩论引用，产出质量会明显更好。

1. `reasoning/trend.py` + `prompts/trend/{weekly,monthly}.j2`；`aipulse trend --range 7d|30d`。
2. `reasoning/debate.py` + 4 个 persona + moderator prompt；`aipulse debate --rounds 1|2`；并发调用。
3. `pipeline/weekly.py`：周度流水线（趋势长文 + LLM 自动选"本周最大争议话题" + 辩论 + 往期预言复盘）。
4. Web 看板点亮「趋势」与「辩论」页面。
5. 可选（默认关闭）：轻量 embedding（sqlite-vec 或本地 bge-small CPU），用于证据检索增强与语义去重；**开启时不得破坏关闭状态下的行为**。

**DoD**：
- [ ] `aipulse trend --range 7d` 产出 2000+ 字带数据表格的长文，且能引用真实的往期预言验证结果
- [ ] `aipulse debate --topic X` 输出 4 视角 + 主持人收敛，含"什么证据会让我改变判断"
- [ ] 4 个 persona 并行执行，日志显示总耗时显著低于串行（有数据佐证）
- [ ] 周报能引用本期辩论；Web 端两个新页面可访问

---

## 17. 测试策略

| 层级 | 内容 | 工具 |
|---|---|---|
| 单测 | 解析器（fixtures 驱动）、打分公式、去重算法、时间窗、prompt 渲染 | pytest |
| 网络 mock | 所有 HTTP 走 `HttpClient`，用 `respx` 拦截 | respx |
| LLM mock | `FakeLLM` 返回固定结构化结果，`--no-llm` 模式跑通全链路 | 自研 |
| 故障注入 | 单源 500 / 超时 / 429 / 空返回 / HTML 结构变更（用失效 fixture） | pytest |
| 契约测试 | LLM 输出 schema 校验，含"非法 JSON → 修复重试"用例 | pytest |
| 集成 | `aipulse daily --skip-llm` 端到端（本地 SQLite 临时库） | pytest + tmp_path |
| 覆盖率 | 目标：`collectors/` ≥80%，`analysis/` ≥85%，`reasoning/` ≥60%（LLM 部分靠 mock） | pytest-cov |

**CI 必须能在无密钥环境通过**：所有涉及真实 API 的测试用 `@pytest.mark.skipif(not os.getenv("AIPULSE_LLM__API_KEY"))` 隔离。

---

## 18. 风险、合规与运维

| 风险 | 影响 | 应对 |
|---|---|---|
| GitHub Trending HTML 改版 | 采集归零 | 解析器快照测试 + 空结果自动降级 Search API + 日志告警 |
| arXiv 限流 3 req/s | 采集中断 | 强制 sleep + 退避 + 缓存；单源失败隔离 |
| Reddit 强制 OAuth | RSS 降级丢 score | 默认 RSS；提供 OAuth 配置路径；score 缺失时用评论数与 LLM 判断弥补 |
| 中文 RSS 源失效 | 新闻板块空 | M0 探测阶段逐个验证；维护备选源清单；提供 `inbox` 手动投喂 |
| LLM 输出不稳定 | 报告质量波动 | 结构化 + 校验 + 修复重试 + prompt 版本化 + 可回溯 |
| API 成本失控 | 超预算 | 每日预算硬上限 + 自动降级 + 缓存 + `llm_usage` 可审计 |
| 数据合规 | 版权/隐私 | 只存标题+摘要+指标，**不全文转载**；标注来源与原链接；遵守各站 robots.txt 与 User-Agent 要求；Reddit 内容遵循其 48 小时删除同步策略 |
| Actions 无法持久化 SQLite | signals 历史丢失 | 报告文件 commit + cache 尽力恢复 + 关键增速数据落 `data/reports/.../signals.json` |

### 18.2 M0 探测实证：网络与解析层的已知问题（v1.4 归档，M1 直接复用这些结论）

以下均为 M0 真实探测中遇到的问题及已验证的解决办法，**M1 编写采集器时直接采用，不要重新踩一遍**：

| # | 问题 | 现象 | 已验证的解决办法 |
|---|---|---|---|
| 1 | **DNS 污染** | `huggingface.co`、`www.reddit.com`、`importai.substack.com` 解析到无关网段（Facebook/Teredo）后连接超时 | 无法在代码层解决 → 按 §5.10 标 `actions_only`；Actions 环境可达 |
| 2 | **连接不稳定** | arXiv / GitHub 本地约 1/3 成功率 | 探测默认 4 次重试 + 10s 连接超时；生产采集沿用 `tenacity` 退避 |
| 3 | **偶发损坏 gzip** | `DecodingError` | ① 把解码失败加入可重试异常；② 对 trending / RSS 请求发 `Accept-Encoding: identity`；③ **注意：坏响应会被写进 HTTP 缓存并持续复现，排查时必须 `--no-cache` 重跑** |
| 4 | httpx 0.28 API 变更 | `Response.ext` 不存在 | 改用 `extensions`；`httpx.Timeout` 必须显式给 `default=` |
| 5 | SQLModel 字段冲突 | 字段名 `date` 与 `datetime.date` 注解冲突 | `from datetime import date as date_type` |
| 6 | alembic autogenerate 漏 import | 生成的迁移缺 `sqlmodel` | 补进 `script.py.mako`；`migrations/` 从 mypy 排除 |
| 7 | 依赖不存在 | `types-feedparser` 在注册表无此包 | 已从 pyproject 移除 |

### 18.3 M1 实证结论与待办（v1.6 归档）

| # | 发现 | 结论 / 处理 |
|---|---|---|
| 1 | **arXiv 索引滞后 3-4 天** | Atom 的 `published` 是提交日，严格 24h 窗口永远采空 → 新增 `lookback_days: 7`（放宽时 warning）。**这是只有真实数据才暴露的问题** |
| 2 | 单 feed / subreddit / 关键词失败拖垮整源 | 三层都改内部隔离，**全部失败才判源级失败** |
| 3 | HN 全关键词失败时静默返回空 | 会伪装成"今天没热点" → 显式抛 `CollectorError`，区分"真为空"和"全挂了" |
| 4 | 本地库缺 `skip_cluster` 列导致崩溃 | 迁移已生成但未执行 → pipeline 入口加 `ensure_schema()` 自动 upgrade 到 head |
| 5 | Trending 页面约 1/3 概率超时 | 改"HTML 失败也走 Search API"，**两通道都拿不到才判死** |
| 6 | 正则 `<p[^>]*>` 误匹配 SVG `<path>` | 改为 `<p(?:\s[^>]*)?>` |
| 7 | `--json` 输出被日志污染 | `--json` 时日志走 stderr，stdout 保持纯 JSON |
| 8 | HF fallback 语义 | 用户只填镜像基址，路径由代码拼接（`{base}/api/daily_papers`） |
| 9 | **本地 RSS 串行 8 feed 耗时 298s** | **M2 待办**：改为每 feed 一个任务并发拉取（仍受全局并发 6 限制）。逐 feed 隔离已就位，改造风险低 |

**M1 成果**：142 passed（M0 时 64），collectors 覆盖率 87.7%，TOTAL 91%；
真实采集 107 条 / 4 源成功 / 2 源按设计跳过 / 0 失败 / 退出码 0。

### 18.4 M3a 实证结论（v1.8 归档）

| # | 发现 | 处理 |
|---|---|---|
| 1 | Typer `invoke_without_command=True` 的回调**在带子命令时也会触发** | 回调首参加 `ctx: typer.Context`，`ctx.invoked_subcommand is not None` 时 `return` |
| 2 | `session.add` 后 `commit` 默认过期 | `Session(engine, expire_on_commit=False)`（M2 已遇，M3a 复现） |
| 3 | ruff B008 误报 `list[str] = typer.Option(...)` | 加 `# noqa: B008` |
| 4 | **★ `json_schema` / `json_object` 两种响应格式共用缓存键会串** | **缓存键追加 `:js` / `:jo` 后缀**。这个坑很微妙：同一 prompt 在自动降级前后会命中错误的缓存结果 |
| 5 | 模糊拦截需防"过度拦截" | 已加负向用例：`"该模型不可能在 30 天内发布"` 不应被误伤（"不可能"是可证伪的否定断言） |

**M3a 成果**：229 passed（M2 时 180），TOTAL 88%，`openai_compat` 覆盖率 **94%**（改造目标 ≥80% 达成）。
8 种模糊句拦截 + 1 个负向防误伤用例。**预言尚未闭环**（`verify` / `review` / `stats` 为占位），符合 M3a 设计。

### 18.5 M3b 实证结论（v1.10 归档）

| # | 发现 | 处理 |
|---|---|---|
| 1 | mypy strict：`dict[str, Any]` 存处理器导致返回值推断为 `Any` | 用 `Callable[...]` 类型别名精确标注 |
| 2 | `float(dict.get(...))` 触发 `Any \| None` | 先取列表再 `if v is not None` 过滤 |
| 3 | 误写 `# type: ignore[return-value]`（实际错误码是 `no-any-return`） | 改用 `cast(Verdict, parsed)`。**不要凭印象写错误码，mypy 会报"未使用的 ignore"** |

**M3b 成果**：272 passed（M3a 时 229，+43），TOTAL 88%，`analysis/stats` 覆盖率 100%。
**★ 预言系统闭环**：off 档实测 `llm_usage` 行数 = 0，即零 API 花费完成
"手写预言 → 到期自动判定 → 记分板更新"全链路。

### 18.6 hybrid 真实运行实证（v1.11 归档）

**首次真实 hybrid 运行（run 38930745578，1m3s 全绿）**：
- `mode: hybrid` 生效，DeepSeek 真实调用 HTTP 200，`degraded: false`
- `generated: 4, inserted: 4, dropped: []` —— 4 条预言**全部带量化判据**，质量符合预期
- `collect: 7 源全通 / 0 失败 / 166 条`

**修掉的 5 个 bug（全部只有真实运行才暴露）**：

| # | bug | 说明 |
|---|---|---|
| 1 | `effective_mode` 缺 `base_url` 判断 | 配 key 没配 base_url → daily 全线崩溃，**违反红线 9** |
| 2 | `AIPULSE_*` env 覆盖全线失效 | yaml 字面量当 init kwargs，pydantic-settings 下**优先级压过环境变量** |
| 3 | `llm.timeout_s: 120` 是死配置 | 实际吃 HttpClient 的 20s → 改按 fast/strong 分档透传（strong 180s） |
| 4 | 超时记 `predict.llm_failed` | 改记"本次未生成"（warning），不当失败 |
| 5 | 记分板生成时间用 UTC | 改本地时区 |

**★ 教训（值得写进 CODEBUDDY.md）**：这 5 个 bug 加上 M4 的"data/ 目录缺失"，
**全部只有真实运行才暴露**——off 档跑得再久也覆盖不了 hybrid/full 路径。

#### 配置占位符划线原则（v1.11）

yaml 里混用两套机制（字面量 vs `${ENV}` 占位符）会静默失效。划线原则：

| 类型 | 机制 | 项 |
|---|---|---|
| **环境开关** | `${ENV}` 占位符（可覆盖） | `mode` / `log_level` / `llm.enabled` / `fast_model` / `strong_model` / `timeout_s` / `timeout_strong_s` / `budget.daily_limit_cny` |
| **算法阈值** | 字面量（要 git 版本化、可复现） | `verify.*` / `signals.*` / `scoring` |

#### 分析窗口的时区论证（v1.11，为什么 cron 改到北京 08:00）

北京 ≈ 美西 +15~16 小时。**AI 新闻高度美国中心**——重要发布多发生在美西工作时间。

| 方案 | 窗口（换算美西） | 问题 |
|---|---|---|
| 原设计（北京 07:00 + "本地今天"） | 只覆盖美西前一日 08:30 后的一小段，**实际约 7 小时** | 窗口严重不足 |
| 方案一（保留"本地今天"，cron 改北京 23:30） | 美西前一日 08:30 → 当日 08:30 | **完全错过当日美西发布**（美西上午 10 点 = 北京次日凌晨 1 点），读到时已滞后约 1.5 天 |
| **方案二（滚动 24h，cron 北京 08:00）** ✅ | 美西前一日 17:00 → 当日 17:00 | **完整覆盖当日美国工作日**，AI 新闻主战场全在窗口内 |

**结论：采用方案二。** 代价是"日报"跨两个自然日（覆盖"截至 08:00 的过去 24 小时"）——
对每日学习而言，**新鲜度 > 日历整齐**，这个代价值得。

**★ 结构要求**：collect 与 analyze **必须共用同一个 window 对象**，不得各自独立计算。
本次 bug 的本质就是两处独立计算，改了一处另一处不知道。

### 18.7 M4 收口实证与主编点评样本（v1.13 归档）

**收口运行（run 38993912848）**：hybrid / `degraded=false` / 7 源全通 164 条 /
生成 5 条预言 / **主编点评非空** / 1m24s（改 fast 档后从 2m38s 降下来）。

#### 主编点评实证样本（★ 对 M6a 有直接参考价值）

> **headline**：智能体评测告别温室：FDE-Gym 与 MAI-Gym 同日把靶心对准真实交付与 GUI 环境
>
> **editor_note**：今天真正值得记一笔的不是某个模型刷榜，而是"交付"这个词开始出现在评测论文标题里……
> 另一个交叉信号是递归自我改进的三篇论文都在做同一件事：冻结权重、改脚手架……
> **反直觉的一点**：Claude 今天在 HN 上最热的两条都不是模型能力，而是团队怎么做 code review……
> 最后提醒一句：ai-job-search 这类工具热度过高但风险被低估……

**这段点评展示了四个层次**，正是"数据版"给不了的：

| 层次 | 例子 |
|---|---|
| 具体判断 | 不是模型刷榜，而是"交付"进入评测标题 |
| 交叉信号 | 三篇论文同做"冻结权重、改脚手架" |
| 反直觉观察 | HN 最热的是 code review 而非模型能力 |
| 风险提醒 | 隐私边界需自己兜底 |

**★ 对 M6a 的直接启示**：`brief.j2` 这个 prompt 已经学会了"给判断而非摘要"。
**M6a 的「为什么重要」应复用同一套风格指令**（要求：具体判断 / 交叉信号 / 反直觉 / 风险），
而不是退化成"这条讲了什么"的摘要。这是从真实样本里得到的、比空想更可靠的设计依据。

#### Actions 报告 commit 的正确姿势（v1.13，坑）

**现象**：`git push` 被拒 → 当天报告丢失（报告即数据库，不可恢复）。

| 尝试 | 结果 |
|---|---|
| 直接 `git push` | 被拒即丢 |
| `git pull --rebase` | **同日重跑时报告文件必然内容冲突** → 还是丢 |
| **`git fetch` + `git reset --soft FETCH_HEAD`** ✅ | runner 上除 `data/reports` 外无其他改动，<br>把本次报告作为新提交叠在远端最新之上，**既不冲突也不丢** |

### 18.8 M6a 收尾实证（v1.16 归档）

**M6a 真实运行（run 39014866080）**：hybrid / 7 源 128 条 / 174 条分析 / **brief degraded=false / 四节点评全部非空**。

#### 四节点评真实样本（质量已达预期）

| 节 | 内容 |
|---|---|
| 🎯 核心判断 | Claude 解开 ECDSA 曲线种子来源——证明大模型能在**有客观验证标准的硬问题**上产出可核查推理，而非只写通顺文字 |
| 🔍 交叉信号 | 论文侧 FDE-Gym/MAI-Gym/Terminal-RSI 与社区侧 Claude Code review、官方插件目录**互相印证**：瓶颈已从模型智力转到脚手架 |
| 🔄 反直觉 | 真正被大量使用的不是更强的模型，而是套在现有模型上的提示词与工作流外壳——**模型层边际价值正被脚手架层吸走** |
| ⚠️ 风险提醒 | 生态扩张速度已超过权限审计能力，用户为几个插件可能交出代码库、密钥与本地文件系统 |

#### ★ 意外收获：M6b 的起点比预想的好

**同一份日报的表格中，部分条目已经出现了「为什么重要」与「立场」**：

| 条目 | 为什么重要 | 立场 |
|---|---|---|
| VoiceStudio | 语音克隆这类高敏感能力走向本地化，绕开云端授权与数据留存问题 | 本地化路线在敏感模态上比云端更有长期说服力 |
| claude-plugins-official | 官方收编插件意味着从工具变成平台，第三方技能包将被迫分层 | 平台化必要一步，但审查缺位会放大供应链风险 |
| FDE-Gym | 承认需求模糊与隐性约束才是落地难点，等于给整个 agent 评测体系提出质疑 | 方向正确，但真实交付难以标准化 |
| ECDSA | 密码学结论可被独立验证，让"模型是否真在推理"第一次有了难以造假的检验场 | 今日最具实质意义的一条 |
| secrets 扫描 | 集成生态扩张速度超过用户对权限的理解速度 | 被低估的警报，比任何模型发布都更影响生态长期健康 |

**这说明**：`daily_brief.j2` v3 已让模型**自主挑选**它认为重要的几条做了点评。

**对 M6b 的意义**：
- 不是从零设计 prompt，**而是把"自主挑选几条"变成"Top N 全部覆盖"**
- 现有输出本身就是**最好的风格范本**（比 §18.7 的更早样本更贴近当前 prompt）
- 风险提示：当前是模型自主挑选，**覆盖面不稳定**（有的条目有、有的没有）——
  这正是用户最初反馈的"详略不一"的另一面

#### 待修：跨板块重复

Apple ML Research 同一条目同时出现在 💬 社区舆论 与 🏢 产业与新闻。
**同一 item 出现在多板块时应只保留主板块**（或明确标注"跨板块"），否则日报显得重复。

### 18.9 predict 截断事故实证（v1.17 归档）

**诊断（run 39016308938）——先拿证据再改，这步做对了**：

```
purpose=predict_generate
max_tokens=4000
first_len=3442
first_head={"predictions": [{"statement": "在 30 天内，anthropics/claude-plugins-official ...
            ... "rationale": "当日同时出现 Anthropic 官方插件目录...
retry_len=0          ← 重试直接返回空：reasoner 思维链再次吃满 4000
retry_head=
```

**结论：截断，不是格式问题。** 若没有"打印前 500 字符 + 长度"这一步，就只能猜。

| 修复 | 效果 |
|---|---|
| `max_tokens` 分档 fast 4000 / **strong 8000** | 首次调用即成功 |
| 候选池 Top 20、只给 `id + 标题` | `candidate_pool=20`，输入不再膨胀 |

**结果（run 39018293521）**：`generated=5` / `degraded=false` / 无 retry 无 degraded /
证据对照 10 个 id 全部可查、无池外 id。

> ⚠️ `inserted=0` 是**同日重跑时稳定 id 已存在**，属幂等正常行为
> （前一次 run 39017637884 为 `generated=5, inserted=5`）。

#### ★ 从这次事故得到的两条硬约束

1. **输出必须紧凑**：只返回必要字段（`id + why + stance`），**不回显标题/摘要/完整条目**。
   这不是风格偏好——回显会让输出翻倍，直接撞 `max_tokens`。
2. **"实测没暴露" ≠ "不存在"**：此前判断"无截断迹象"所以没动 max_tokens，
   那是因为当时 items 只有 1 条。**改变数据规模后，必须回归检查所有依赖上下文长度的环节。**

### 20. 项目定位修正：使用反馈驱动的持续迭代（v1.18）

**这不是一个"功能开发完就结束"的项目。**

REA 消失这个 bug 很能说明问题：**它很难提前发现**，
所有测试都是绿的、所有指标都正常，只有真正使用、且对领域有判断的人才会发现
"诶，这么火的项目怎么没了"。

**这类问题对信息汇总类工具尤其致命**——因为用户用它就是为了**不漏掉重要信息**，
而"漏报"恰恰是最难自测、也最伤信任的问题。

**因此项目应确立以下机制**：

| 机制 | 说明 |
|---|---|
| **常态化人工抽检** | 每天看日报时问一句"有没有该出现却没出现的"（比任何自动化指标有效） |
| **关键状态显式暴露** | `llm.degraded` 进简报、证据 id 出对照表、signals 三态可观测 —— **让异常自己浮出来** |
| **快照对比** | 报告每天 commit，可 diff——**异常往往藏在"今天和昨天不一样"里** |
| **反馈闭环留痕** | 用户反馈的问题写进 SSOT 变更摘要与踩坑实录，不修完就忘 |

**一句话**：
> 信息工具的价值不在"功能齐全"，而在"**用户相信它没漏**"。
> 这份信任只能靠持续使用、持续反馈、持续修来建立——**开发完成只是起点**。

**M0 遗留缺口（M1 首步处理）**：`tests/fixtures/reddit_top.json` 缺失（本地不可达）。
处理方式：M1 在 **Actions 环境**下补测（用 `workflow_dispatch` 跑一次 `probe_sources.py` 并下载 artifact），
在此之前 reddit 采集器的单测用 `pytest.skip` **显式标记**，不得静默假装通过。

---

## 19. 决策记录（v1.2：全部确认项已收敛）

### 19.1 已确认的决策（Agent 直接按此执行，无需再问）

| # | 决策项 | 结论 | 决策依据 |
|---|---|---|---|
| 1 | 项目/仓库命名 | **`aipulse`（AI 脉搏）** | 脉搏的三层隐喻完整覆盖产品主线：把脉（每日采样信号）→ 诊断（分析判断）→ 预后（推演预言）。名字短、可作 CLI 名、中英文都好念。若 GitHub 仓库名被占用，加后缀 `-daily` 或改用组织名，包名 `aipulse` 不变 |
| 2 | 开源许可证 | **MIT**（v1.0 的 Apache-2.0 已否决） | 本项目是**应用工具而非基础库**，不涉及专利密集领域，Apache 的明示专利授权条款实际用不上；Apache 还需维护 NOTICE 文件、修改时声明变更，属于过度设计。MIT 文本约 20 行、GitHub 最流行、企业法务审查最快，对吸引使用者与贡献者最有利 |
| 3 | 微信 / X 支持 | **彻底移除**（含 RSS 桥） | X 官方 API 已收费且额度极低、Nitter 大量关停；公众号无公开 API、第三方接口有版权合规风险；RSS 桥需自建长期运维，与单机工具定位冲突。**替代 = `inbox` 手动投喂**（§5.8） |
| 4 | 主力 LLM | **DeepSeek**：`deepseek-chat`（fast）+ `deepseek-reasoner`（strong） | 便宜、中文强、OpenAI 兼容；换厂商只改环境变量不改代码（§8.2） |
| 5 | 里程碑顺序 | **M0→M1→M2→M3→M4(发布与自动化)→M5(深度推演)** | 记分板价值靠时间沉淀，越早自动跑越值钱；长文与辩论无等待期，晚做不损失。详见 §16.0 |
| 6 | Reddit 认证方式 | 先用**免认证 RSS**，跑通后再决定是否申请 OAuth | RSS 够用（≤25 条、无 score），OAuth 需注册应用且要承担合规义务 |
| 7 | 每日预算上限 | **2 CNY/日**（约 0.3 USD） | 按每天简报 1 次 + 预言 1 次 + 验证数次估算，DeepSeek 定价下绰绰有余；超预算按 §8.4 自动降级 |
| 8 | 报告语言 | **中文为主**，术语保留英文 | 面向中文 AI 从业者；英文标题/项目名不强行翻译 |
| 9 | 运行方式 | **WSL 本地 cron + GitHub Actions 双轨** | Actions 保证公开可追溯与"每天真在跑"的观感；本地 cron 保证数据不丢 |
| 10 | HTML 样式 | 极简黑白 + 数据表格（终端友好） | 无需前端构建链，打印与分享都好用 |
| 11 | embedding | **默认关闭**，M5 可选开启（本地 bge-small CPU） | V1 用 TF-IDF 足够；关闭状态下行为不得被破坏 |
| 12 | GitHub Token | **建议配置**（30 req/min vs 10 req/min，且能拿到更全的 repo 信息） | 免费的 fine-grained token，勾选只读权限即可；未配置时自动降级且 doctor 会提示 |
| 13 | 预言记分板 | **作为 README 与 Web 首页的门面** | 本项目最强辨识度资产，且随时间自动变强（自带复利效应） |
| 14 | RSS 源策略 | **英文主干 + 中文补充** | 英文优质源（Simon Willison、Import AI、Latent Space、官方博客、The Verge/TechCrunch/Ars）RSS 极稳定、几乎无营销稿，作为新闻板块基本盘；中文源（机器之心/量子位）标 `optional: true`，失效只告警不阻塞。详见 §5.7 |
| 15 | Reddit 认证 | **先走免认证 RSS**，M1 验收后再评估 OAuth | OAuth 需注册应用 + 承担 Responsible Builder Policy 义务 + 多一套密钥管理，不要提前付这个成本。score 缺失用「排名位次代理 + 该源降权 + LLM 判断」三重补偿。详见 §5.6 |
| 16 | 仓库公开时机 | **M0 即公开**，README 顶部标 WIP | 开发过程本身即说服力（完整 git 历史 + 每阶段验收 + 真实取舍理由），且能早期收到反馈。丢掉"等完美再公开"的负担。详见 §14.2 |
| 21 | **数据源环境分级** | **`availability: always|actions_only`** | M0 实测发现本地 WSL 与 Actions 网络可达性完全不同（reddit/hf/importai 本地 DNS 污染、Actions 可达）。不分级会导致"本地测不到就永久禁用高质量源"。本地跳过且不计失败，Actions 全开。详见 §5.10 |
| 22 | **HF 镜像站** | **只预留 `fallback_endpoints: []` 空字段，默认走官方** | 第三方镜像的可信度与稳定性不受控，开源项目不应替所有用户做这个决定；但留字段让国内用户填一行即可。探测脚本里可自动尝试（那是诊断工具）。详见 §5.4 |
| 23 | **中文源** | **接受现状，定义为「仅标题源」** | 实测机器之心/36氪 已下线或返回 HTML，仅量子位可用且摘要仅 22 字。关键处理：**`title_only` 源不参与 TF-IDF 聚类**（短摘要会污染聚类）。详见 §5.7 |
| 24 | **WSL 网络** | **按无代理推进** | HttpClient 已支持 `HTTP_PROXY/HTTPS_PROXY`，用户后续有代理时配环境变量即可，无需改代码 |
| 18 | **三档运行模式** | **`off` / `hybrid` / `full`，API 从必需降级为可选** | 让零 API 花费的用户也能用（off 档保留采集/打分/聚类/手写预言/自动验证/校准统计全链路）。API 是"让它更好"而非"让它能用"。详见 §8.5 |
| 19 | **手写预言交互** | **参数 + 缺参自动降级为交互式向导** | 纯参数方案用户要手写 JSON 判据，太痛苦会导致功能被弃用；纯向导无法脚本化。混合方案只比纯参数多约 40 行，却两者兼得。详见 §11.4.2 |
| 20 | **量化判据** | **可选字段 + 内置模板库** | 带阈值的预言到期查表即判，零成本；且填判据的过程倒逼预言写得可证伪。不强制，语义型预言仍走人工/LLM。详见 §11.5 |
| 17 | 日报触达 | **文件 + Web 看板为主，架构预留 Notifier 抽象** | 先用文件+看板跑两周；若真出现"产出没人看"，再花半小时加邮件推送。这是最容易补的一环，不值得提前设计。预留渠道：SMTP / Telegram / 飞书 / 桌面通知（**现在都不实现**）。详见 §11.2 |

### 19.2 运行后再调的参数（不阻塞开工，属于"跑起来看效果再调"）

这些**不需要现在问**，因为答案取决于真实数据。做法是：先按默认值跑，在对应里程碑验收时用真实结果判断。

| # | 参数 | 默认值 | 何时用真实数据回调 |
|---|---|---|---|
| A | 每日新生成预言条数 | 5 | M3 验收后：若校验器频繁拒收导致实际只产出 1-2 条，说明 prompt 需要改而非放宽标准 |
| B | 预言 horizon 组合 | 7 / 30 / 90 | M3 验收后：观察各期限的验证成功率，若 7 天太短可上调 |
| C | 简报板块划分 | 开源项目 / 论文研究 / 社区舆论 / 产业新闻 | M2 验收后：按实际数据分布调整，若某板块长期为空则合并 |
| D | 热度打分权重（`scoring.yaml`） | 见 §9.1 | M2 验收后：这是**最需要调**的地方，用 Top10 结果是否符合直觉来校准 |
| E | Reddit 是否升级 OAuth | RSS | M1 验收后：看 r/LocalLLaMA 条目在简报中的实际占比与质量 |
| F | 是否加邮件推送 | 否 | 跑两周后：若你发现自己忘了打开看板，再花半小时加 |

### 19.3 已确认，无需再讨论的项

以下在原 v1.0 中曾列为待确认，现已明确，**Agent 不必再问**：
- 微信 / X 支持 → 彻底移除（§5.8）
- 许可证 → MIT（不是 Apache-2.0）
- 项目名 → `aipulse`
- LLM 厂商 → DeepSeek
- 里程碑顺序 → M4 发布与自动化 / M5 深度推演
- embedding → 默认关闭

### 19.5 ★ 文档维护日志规范（v1.18 固化）

**问题**：文档版本（vN）与代码版本（tag）是两套独立编号。
没有日志时，只知道"文档是 v1.18"，**但不知道它描述的是哪个状态的代码**——
而这才是最关键的信息。

**规范**：

1. 每次文档维护，在 `docs/文档维护日志.md` **顶部追加一行**（倒序，新的在上）
2. 格式：`| 文档版本 | 对应 tag / commit | 日期 | 一句话总结 |`
3. **★ 必须先提交代码并打 tag，再刷新文档**——否则 tag 栏写不出来
4. 两份 SSOT 版本号必须一致，不一致视为维护未完成
5. Agent 不得修改该文件（与 SSOT 同样的只读约定）
6. **新会话开场白固定包含**："先读 `docs/文档维护日志.md` 最后一行确认基线"

**为什么值得做**：

| 场景 | 没有日志 | 有日志 |
|---|---|---|
| 继续维护 | 不知道上次改到哪 | 一眼看到基线 |
| **Agent 中断重启** | 新会话不知道上一版写了什么 | **唯一可靠的锚点**，甚至能自己判断文档是否落后于代码 |
| 日后回溯 | 无从查证 | tag + 一句话总结，可精确定位 |

**顺带价值**：它让"先提交再刷新文档"这条纪律**可执行**——
写不出 tag 栏就说明顺序错了。

### 19.4 SSOT 文档归属与同步约定（v1.7）

**问题**：设计文档由项目负责人（在沙箱/本地）产出，而 Agent 在仓库内也会改 `docs/`，
两处同时修改会产生**版本漂移**——SSOT 出错的代价极高（Agent 会按错误文档写代码）。

**约定：文档以项目负责人产出的全量版本为唯一权威，每次覆盖仓库内 `docs/`。**

| 角色 | 职责 |
|---|---|
| 项目负责人 | 产出 `AI_Pulse_设计方案_vX.md` 与 `AI_Pulse_Agent开发执行手册_vX.md` 的**全量版本** |
| 项目负责人 | 每轮开始时把这两份文档**覆盖**到仓库 `docs/` |
| Agent | **只读**这两份 SSOT；可在 `docs/开发日志.md`、`docs/数据源手册.md`、`docs/新增数据源指南.md` 中追加内容 |
| Agent | **不得修改** SSOT 两份文档（已在红线中约束） |

**为什么是全量覆盖而非增量补丁**：补丁容易冲突或漏合，而 SSOT 出错会导致 Agent 按错误规格写代码，
代价远高于"每轮拷贝一次文件"。

### 19.5 关于"预言数量"的一条提醒

预言条数**不是越多越好**。样本量决定了统计量的可信度，但每条预言的质量决定了这个项目的声誉。建议：**每天 3-5 条，宁缺毋滥**——一条"3 个月内会出现 X"且最终被验证的预言，比 20 条含糊其辞的预言有价值得多。校验器（§10.2）会拒收不可证伪的条目，此时宁可当天只产出 2 条，也不要为了凑数放宽标准。

**★ v1.11 补充：证据 id 还必须做存在性校验**（详见 §10.2.1）——仅有"≥2 条证据"的数量校验是不够的，
真实运行已证实模型会产出不存在的 id。

---

## 附录 A · 已核实的数据源事实（2026-10 核对，供 Agent 直接引用）

| 源 | 端点 | 认证 | 限速/限制 | 备注 |
|---|---|---|---|---|
| GitHub Trending | `https://github.com/trending?since=daily[&l=python]` | 无 | 约每 6h 更新；HTML 不稳定 | 建议同时用 Search API 交叉验证 |
| GitHub Search API | `https://api.github.com/search/repositories?q=created:>{date}&sort=stars` | Token（建议） | 无 token 10 req/min；有 token 30 req/min | 排序按总 star，非增速 |
| arXiv API | `http://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=200` | 无 | **3 req/s**（超限 503） | Atom XML，建议 feedparser；需描述性 UA |
| HF Daily Papers | `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD&limit=50` | 无（只读公开） | 未公开限流，建议温和 | 与 arXiv 重叠，需按 arxiv_id 交叉去重 |
| HF Paper 详情 | `https://huggingface.co/api/papers/{arxiv_id}` | 无 | — | upvotes、AI 摘要、关联 repo |
| HF 论文→资源 | `https://huggingface.co/api/arxiv/{arxiv_id}/repos` | 无 | — | models/datasets/spaces，判断可复现性 |
| HN Algolia | `https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&numericFilters=created_at_i>{ts},points>30` | 无 | 宽松 | 另有 `/api/v1/items/{id}` 一次取全评论树 |
| HN Firebase | `https://hacker-news.firebaseio.com/v0/item/{id}.json` | 无 | — | 取单条最新分数 |
| Reddit OAuth | `https://oauth.reddit.com/r/{sub}/top?t=day&limit=50` | **必须 OAuth** | 100 QPM / client_id（10min 滑动） | UA 必须 `<platform>:<appid>:<ver> (by /u/<user>)` |
| Reddit RSS | `https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day` | 无 | 按 IP 限流 | ≤25 条、无 score，V1 默认走这条 |
| RSS/Atom | 各站 feed | 无 | — | feedparser 解析；中文站需逐个验证可用性 |

## 附录 B · 给 Agent 的"开工第一句 Prompt"模板

> 你是一名资深 Python 工程师。请阅读 `/path/to/aipulse/docs/AI_Pulse_设计方案.md` 与 `docs/AI_Pulse_Agent开发执行手册.md`，这是本项目的唯一事实来源。
> 现在只执行 **M0 阶段** 的任务清单（§M0），严格按文档中的目录结构、技术选型与验收标准实现。
> 规则：① 不得跳过 `scripts/probe_sources.py` 这一步，所有解析逻辑必须基于 `tests/fixtures/` 的真实响应；② 每个文件写完后立刻补对应单测；③ M0 的 DoD 全部满足后停下，输出验收清单让我确认，不要开始 M1；④ 遇到文档未覆盖的决策点，先问我，不要自行发挥。
