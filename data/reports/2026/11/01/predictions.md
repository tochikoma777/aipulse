## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| Anthropic 会在 30 天内把「禁止使用 Claude 对电子游戏进行逆向工程或克隆」写入公开可查的使用政策文档（Usage Policy / AUP 或同等法律条款页），而非仅停留在支持文章与媒体回应层面。 | policy | 0.60 | 30 天 | 2026-12-01 | 截至到期日：在 anthropic.com 的 Usage Policy / Acceptable Use Policy / Consumer Terms 等法律条款页面中，能检索到同时涉及 reverse engineering / decompilation 与 video game（或 game cloning）的明文条款条目，算命中；若这些页面仍无对应条款（相关内容只出现在 support 帮助中心文章、新闻稿或媒体转述中），算落空。 | `it_71145972f162b48a` `it_94697ec49ac5116b` |
| 「多个 ≤32B 开源模型（Qwen3 系）组成的多智能体集成超过单一更大模型」这一路线，将在 30 天内出现至少 2 个可独立核查的公开复现或扩展（GitHub 仓库或公开基准提交）。 | capability | 0.50 | 30 天 | 2026-12-01 | 截至到期日：在 GitHub 上能检索到 ≥2 个在该日期之后创建或重大更新的仓库，其 README 明确描述「N 个 Qwen3-27B/32B 级模型的集成或投票/辩论编排在 LiveCodeBench Hard 或同类代码基准上超过单一大模型」，且 star ≥200；或在 LiveCodeBench 等公开榜单/论文预印本中出现 ≥2 条对应的第三方提交。满足则命中，只有原始 Memdoor 一个来源则落空。 | `it_1d109e872ed6cf66` `it_82785ab4f152db3e` `it_9780abeb5fce378d` |
| 90 天内，会出现至少一个以 Factorio 或同类自动化建造游戏为环境的公开 LLM 智能体评测（arXiv 论文或 star ≥1000 的开源仓库），把「长程生产链规划」作为可量化指标。 | research | 0.45 | 90 天 | 2027-01-30 | 截至到期日：arXiv 检索到 ≥1 篇标题或摘要明确以 Factorio / 自动化建造游戏为评测环境的 LLM agent 论文，或 GitHub 上 ≥1 个该类评测环境仓库 star ≥1000 且 README 给出可复现的模型得分表。二者满足其一算命中；仅有模型厂商博客宣称「能通关」而无公开环境与评测协议算落空。 | `it_82785ab4f152db3e` `it_aa4997f9eba15998` |
| 90 天内，至少一家主流安全厂商（CrowdStrike、Google Mandiant、Microsoft、Palo Alto Networks 之一）在公开威胁情报报告中，把「用 LLM 对受害者/目标按可变现价值排序」列为已观测到的真实攻击手法。 | business | 0.40 | 90 天 | 2027-01-30 | 截至到期日：在上述任一厂商官网发布的威胁情报/年度报告（非博客观点文章）正文中，出现明确描述攻击者使用 LLM 或 AI 对被入侵主机/受害者按价值、支付能力或资产重要性进行排序或分级的段落，并在报告中将其标注为已观测活动（observed in the wild）算命中；若仅以「未来风险」或「可能被滥用」形式提及则落空。 | `it_5b0ac3b976a1c0a5` `it_ebfcd2cb02eb3c5c` |
| 30 天内，Anthropic 会在 Claude Code 官方文档或官方仓库中新增第三方「技能/插件」（skills/plugins）的安装与分发机制说明，而不仅依赖社区仓库自行分发。 | product | 0.40 | 30 天 | 2026-12-01 | 截至到期日：docs.anthropic.com（或 docs.claude.com）的 Claude Code 文档区，或 anthropics 组织下的官方 GitHub 仓库，出现独立章节说明如何安装、注册或分发第三方 skill/plugin（含目录结构约定或清单文件格式）。出现算命中；若社区侧仍只能通过 README 手动拷贝文件、官方文档无对应章节则落空。 | `it_f859b2d15e1457f4` `it_81446f2462dee9e2` `it_ebfcd2cb02eb3c5c` |

### 证据条目对照（人工核验用）

- `it_71145972f162b48a` → Anthropic takes steps to block Claude from reverse-engineering video games
- `it_94697ec49ac5116b` → Anthropic's Claude AI blocks video game cloning and reverse-engineering
- `it_1d109e872ed6cf66` → Memdoor: A team of 5 Qwen3.8-27B models beats Fable 5 on LiveCodeBench Hard
- `it_82785ab4f152db3e` → GPT-5.6 Sol can beat Factorio on peaceful mode
- `it_9780abeb5fce378d` → HKUDS/DeepTutor
- `it_82785ab4f152db3e` → GPT-5.6 Sol can beat Factorio on peaceful mode
- `it_aa4997f9eba15998` → The Impact of Generative AI on Critical Thinking: Self-Reported (2025)
- `it_5b0ac3b976a1c0a5` → Malware uses LLMs to rank victims by how much they're worth
- `it_ebfcd2cb02eb3c5c` → thedotmack/claude-mem
- `it_f859b2d15e1457f4` → obra/superpowers
- `it_81446f2462dee9e2` → mattpocock/skills
- `it_ebfcd2cb02eb3c5c` → thedotmack/claude-mem

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-01T04:12:26.458936+00:00_
