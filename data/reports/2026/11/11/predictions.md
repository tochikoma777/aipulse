## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| 在 30 天内，至少一家 Anthropic 之外的主流编程智能体厂商（OpenAI Codex、GitHub Copilot、Cursor、Google Gemini CLI、Vercel 之一）会在官方文档或官方 changelog 中正式支持 SKILL.md 式的「agent skills」目录规范。 | community | 0.70 | 30 天 | 2026-12-11 | 截至到期日，检查上述五家厂商的官方 docs 站点与 changelog：若出现任一页面明确记载对 skills 目录/SKILL.md 的加载与执行支持（含 beta/preview 标记），记为命中；若五家均无官方记载（仅社区博客、第三方 fork 或非官方 issue 讨论不算），记为落空。 | `it_85641ad38767c9cc` `it_5322fa73dc282dcd` `it_81446f2462dee9e2` |
| 90 天内，Apple 会公开发布一款第一方 macOS 应用（App Store 上架或 developer.apple.com 可下载的公测/正式版），用于在本机运行大语言模型，且支持至少 2 个非 Apple 自研的第三方模型家族。 | product | 0.60 | 90 天 | 2027-02-09 | 截至到期日，若 Apple 官网或 Mac App Store 出现该应用的公开下载/上架页面，且文档或应用内列出 ≥2 个第三方模型家族（如 Llama、Qwen、Gemma、Mistral 等）可直接加载，记为命中；若仅停留在媒体报道、无公开可下载版本，或仅支持 Apple 自家模型，记为落空。 | `it_77d255b4e9ac58d2` `it_93e99bdd1f801572` |
| 90 天内，GitHub 会出现至少一个基于 few-step / condition-shifting 思路的开源流式视频生成实现，star ≥ 1000，且作者给出在单张消费级 GPU 上 ≥16 FPS 的可复现 benchmark。 | research | 0.40 | 90 天 | 2027-02-09 | 截至到期日，在 GitHub 检索视频生成类仓库：若存在任一仓库同时满足 (a) star ≥ 1000、(b) 采用 few-step 或 condition shifting 类少步数流式方案、(c) README 或论文给出单卡消费级 GPU（如 RTX 4090）上 ≥16 FPS 的实测数据，记为命中；若仅有论文无开源代码，或仅有代码但无 ≥16 FPS 实测，记为落空。 | `it_04dc57421a57cfcf` `it_773a5466ce19145f` |
| 90 天内，Vercel 会把 vercel-labs/agent-browser 转为正式产品：在 vercel.com 官方产品页或 AI SDK 官方文档中提供带版本号、有 SLA 或计费条目的浏览器智能体能力。 | business | 0.50 | 90 天 | 2027-02-09 | 截至到期日，若 vercel.com 域名下出现产品页或 AI SDK 文档章节，明确提供该浏览器智能体能力的稳定版本（非 labs/实验目录）、且附带定价、配额或 SLA 说明之一，记为命中；若该能力仍只存在于 vercel-labs 组织下、无官方文档入口与计费/配额说明，记为落空。 | `it_8292947de71d6092` `it_f58332e28bbdf770` |
| 90 天内，Home Assistant 官方（Nabu Casa）会在其官方文档中发布一等公民的 MCP 支持页面（内置 MCP 服务器或客户端集成），而非仅依赖第三方社区仓库。 | community | 0.45 | 90 天 | 2027-02-09 | 截至到期日，若 home-assistant.io 官方文档出现 MCP 相关集成页面（标注为官方集成或官方附加组件，含安装与配置说明），记为命中；若 MCP 支持仅存在于第三方仓库（如 homeassistant-ai/ha-mcp）或仅出现在社区论坛与 feature request，记为落空。 | `it_93e99bdd1f801572` `it_8292947de71d6092` `it_ec8c7e5f32546a34` |

### 证据条目对照（人工核验用）

- `it_85641ad38767c9cc` → anthropics/skills
- `it_5322fa73dc282dcd` → addyosmani/agent-skills
- `it_81446f2462dee9e2` → mattpocock/skills
- `it_77d255b4e9ac58d2` → Apple has new Mac app coming to make running local AI models easy
- `it_93e99bdd1f801572` → homeassistant-ai/ha-mcp
- `it_04dc57421a57cfcf` → Few-Step Streaming Video Generation via Condition Shifting
- `it_773a5466ce19145f` → PhysOPSD: Code as Privilege for Physically Plausible Video Generation
- `it_8292947de71d6092` → vercel-labs/agent-browser
- `it_f58332e28bbdf770` → Show HN: Get your coding agent off ~2019 JavaScript, onto modern web primitives
- `it_93e99bdd1f801572` → homeassistant-ai/ha-mcp
- `it_8292947de71d6092` → vercel-labs/agent-browser
- `it_ec8c7e5f32546a34` → milind-soni/OpenMausBot

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-11T04:36:16.115512+00:00_
