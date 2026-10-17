## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| Anthropic 会在 30 天内为 Claude Code 增加内置的自动化代码审查能力（如 /review 类命令或官方 PR 审查集成），并在官方文档或 CHANGELOG 中明确列出。 | product | 0.45 | 30 天 | 2026-11-16 | 截至到期日，若 docs.anthropic.com 或 Claude Code 官方 CHANGELOG 中出现可独立调用的仓库级/PR 级自动化 code review 功能条目，判为命中；若仅有博客文章、客户案例或第三方 GitHub Action 而无官方内置功能条目，判为落空。 | `it_7fd7e06ab2f4b840` `it_752e25023358d2db` |
| 30 天内，GitHub 上会出现至少 2 个以「自进化 agent harness（自动改写自身 prompt/记忆/工作流脚手架）」为主题、且 star 数 ≥ 500 的公开仓库。 | research | 0.40 | 30 天 | 2026-11-16 | 截至到期日，在 GitHub 搜索 'self-evolving agent harness' / 'self-rewrite scaffold' 等关键词，若存在 ≥2 个 2025 年后创建、star ≥ 500、且 README 明确描述在不改模型权重前提下自动改写自身 prompt/记忆/工作流的仓库，判为命中；仅有学术论文或无达到 star 阈值的仓库，判为落空。 | `it_56b180964d659d0b` `it_e0013168d05fc73f` `it_d729d4595639862e` |
| MAI-Gym 与 OpenGCUA 两者中至少一个会在 30 天内公开可访问的代码仓库或数据集（GitHub repo 或 HuggingFace dataset），且页面在到期日仍可正常打开。 | research | 0.60 | 30 天 | 2026-11-16 | 截至到期日，检查 MAI-Gym 与 OpenGCUA 是否在 GitHub 或 HuggingFace 上存在官方（作者/机构账号）发布的 repo 或 dataset：若两者中任一存在且可访问、含 README 与至少一份环境或评测数据，判为命中；若两者均无可访问的官方产物，判为落空。 | `it_3fdde7c257bf92e1` `it_ac9d0bbaa3525b0a` `it_5ad7c46a32ced559` |
| 30 天内，Hacker News 首页会再出现至少 1 条把 llama.cpp/GGUF 模型跑在非 PC 消费硬件（游戏机、手机、车机、路由器、单板机等）上的帖子。 | hardware | 0.70 | 30 天 | 2026-11-16 | 截至到期日，在 HN Algolia 检索近 30 天且 points ≥ 100、进入过 front page 的帖子，若存在 ≥1 条标题或正文明确描述在游戏机/手机/车机/路由器/单板机上原生运行 llama.cpp 或 GGUF 模型（非普通 PC/服务器/Mac），判为命中；完全没有此类帖子判为落空。 | `it_b8a37debaf4717f6` `it_98e6a11f87f3c75f` `it_c19e7ef010f7b535` |
| 90 天内，至少一家主流 AI 编码工具（Cursor / GitHub Copilot / Claude Code / OpenAI Codex 之一）会在官方文档或设置项中新增「读取密钥与敏感文件需用户显式授权」的明确机制说明。 | policy | 0.45 | 90 天 | 2027-01-15 | 截至到期日，检查上述四家产品的官方文档或产品设置页：若任一出现明确的凭据/敏感文件访问需用户显式授权（如目录级 allowlist、secret 扫描豁免开关、按路径授权）的条款与对应设置项，判为命中；若仅有笼统的隐私政策而无针对密钥/敏感文件的显式授权机制，判为落空。 | `it_4b8ac65f24d26463` `it_752e25023358d2db` |

### 证据条目对照（人工核验用）

- `it_7fd7e06ab2f4b840` → How the Claude Code team does code review
- `it_752e25023358d2db` → MadsLorentzen/ai-job-search
- `it_56b180964d659d0b` → Self-Evolving Agent Harness
- `it_e0013168d05fc73f` → Terminal-RSI: Recursive Self-Improving Terminal Agents via Recursive Self-Rewrite and Policy-Refine
- `it_d729d4595639862e` → Mosaic: Multi-Session Agentic Reinforcement Learning
- `it_3fdde7c257bf92e1` → MAI-Gym: An Open All-in-One Platform for GUI Agent Evaluation and RL Training across Mobile and Computer Environments
- `it_ac9d0bbaa3525b0a` → OpenGCUA: Toward a Fully Open Stack for Generalist Computer Use
- `it_5ad7c46a32ced559` → RoTA-Bench: Evaluating 3D Spatial Reasoning through Interactive Projection Alignment
- `it_b8a37debaf4717f6` → Llama.cpp on a jailbroken PS5: run any GGUF model natively on the console
- `it_98e6a11f87f3c75f` → Apple ML Research: Muse Spark Open with MLX on Mac Studio
- `it_c19e7ef010f7b535` → You could have invented transformers from memory
- `it_4b8ac65f24d26463` → I never authorized an integration that scans my secrets
- `it_752e25023358d2db` → MadsLorentzen/ai-job-search

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-10-17T02:53:29.930165+00:00_
