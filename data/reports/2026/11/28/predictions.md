## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| Claude 在 ML 研究任务中「破坏/偷懒」的讨论将升级为可复现的公开评测，30 天内至少出现 1 个 star>500 的第三方基准仓库专门测量 Claude 类模型的 agentic sabotage 行为。 | research | 0.55 | 30 天 | 2026-12-28 | 截至到期日，GitHub 上存在至少 1 个 star>500 的仓库，其 README 明确以「sabotage / sandbagging / reward hacking in agentic ML tasks」为评测目标并覆盖 Claude 系列模型；若仅有讨论帖而无此类仓库则算落空。 | `it_138e1e18872d9e9b` `it_27d1d8a4f04e089d` |
| 面向 AI coding agent 的「轻量原生 harness」将出现明显分化：30 天内 Prospero 类 ImGui 原生 harness 在 GitHub 上的 star 数将超过 obra/superpowers 当前 star 数的 50%。 | product | 0.40 | 30 天 | 2026-12-28 | 到期日抓取两仓库 GitHub star 数：若 Prospero 仓库 star ≥ superpowers 仓库 star × 0.5 则命中；若 Prospero 仓库不存在或 star < 该阈值则落空。 | `it_1806f3bb38b7c0f3` `it_f859b2d15e1457f4` |
| 单卡（GB10 级）跑小模型的高吞吐推理方案将在 30 天内被至少 2 个独立仓库复现，并公开 ≥100 tok/s 的基准数据。 | hardware | 0.60 | 30 天 | 2026-12-28 | 截至到期日，GitHub 上存在 ≥2 个与原作者不同的仓库，各自 README 或 benchmark 文件给出在单张 GB10（或同级单卡）上 vLLM 推理某小模型 ≥100 tok/s 的实测数字；若只有原帖一个来源则落空。 | `it_061346cb2f74644b` `it_ed75bf498e47451e` |
| 「从零/低成本训练小模型」类教学仓库（minimind 型）将在 30 天内新增至少 1 个 star>3000 的同类竞品仓库。 | community | 0.50 | 30 天 | 2026-12-28 | 到期日检索 GitHub：若存在至少 1 个非 jingyaogong/minimind 的仓库，主题为「从零训练小语言模型/低成本复现」，且 star>3000、创建时间在预言发布之后，则命中；否则落空。 | `it_ed75bf498e47451e` `it_42f8ff418476e850` |
| AI 训练数据交易将出现可公开查证的价格/条款披露：30 天内至少 1 家数据供应商或买方公开披露按 token 或按小时计价的具体数字。 | business | 0.35 | 30 天 | 2026-12-28 | 到期日检索：若出现 ≥1 篇由数据供应商、AI 实验室或行业媒体发布的报道/公告，明确给出训练数据每 token、每千词或每标注小时的美元价格区间，则命中；若仅有「市场火热」类定性描述则落空。 | `it_42f8ff418476e850` `it_8d57cc2cadedeb4f` |

### 证据条目对照（人工核验用）

- `it_138e1e18872d9e9b` → Claude sabotaging ML research tasks?
- `it_27d1d8a4f04e089d` → elementalsouls/Claude-BugHunter
- `it_1806f3bb38b7c0f3` → Prospero: Bloat-free, native AI coding harness with ImGui
- `it_f859b2d15e1457f4` → obra/superpowers
- `it_061346cb2f74644b` → Show HN: Getting 101 tok/s from Inkling 2 Mini in vLLM on one GB10
- `it_ed75bf498e47451e` → jingyaogong/minimind
- `it_ed75bf498e47451e` → jingyaogong/minimind
- `it_42f8ff418476e850` → Inside the AI Training Data Market — Gabe Greenberg, G2i
- `it_42f8ff418476e850` → Inside the AI Training Data Market — Gabe Greenberg, G2i
- `it_8d57cc2cadedeb4f` → firecrawl/firecrawl

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-28T01:35:23.604623+00:00_
