## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| Notion 官方 MCP 注入隐藏 upsell 指令一事将引发至少一个第三方 MCP 客户端（如 Claude Desktop 插件、开源 agent 框架）在 30 天内加入对 MCP 工具返回内容的指令过滤或审计功能。 | product | 0.65 | 30 天 | 2026-12-27 | 截至到期日，在 GitHub 上检索到 ≥1 个 star>500 的 MCP 客户端/框架仓库发布 release 或 PR，明确包含对 MCP server 返回文本中隐藏指令（prompt injection / upsell）的检测、过滤或告警功能；若 30 天内无此类公开代码变更则算落空。 | `it_8e49016f829cbdac` `it_f859b2d15e1457f4` `it_f09a3afb4ff397a9` |
| OpenAI 削减 GPT-6.2 用量（Astra 限额收紧 40%、Sol 收紧 25%）后 30 天内，至少一个主流第三方 API 聚合/路由平台（如 OpenRouter 类）上线针对 GPT-6.2 系列的自动降级或跨模型 fallback 路由功能。 | business | 0.60 | 30 天 | 2026-12-27 | 截至到期日，在任一公开可访问的第三方 LLM 路由/聚合平台（需有公开文档或 changelog）上，出现明确针对 GPT-6.2 系列限额收紧的自动 fallback/降级路由配置项或公告；若 30 天内无此类公开功能或公告则算落空。 | `it_244a3e8cb4f170fa` `it_536be0c2a1d62b85` |
| AMD 专用 llama.cpp fork 出现后 90 天内，上游 ggml-org/llama.cpp 主仓库将合并至少一个明确标注 AMD 后端优化的 PR。 | hardware | 0.55 | 90 天 | 2027-02-25 | 截至到期日，ggml-org/llama.cpp 主仓库的 merged PR 中，存在 ≥1 个标题或描述明确提及 AMD（ROCm/HIP/AMD GPU）性能优化的合并记录，且合并时间晚于本预言发布日；若无此类合并则算落空。 | `it_1d45997e4997625f` `it_ed75bf498e47451e` |
| HKUDS/CLI-Anything 与 obra/superpowers 这类'把 CLI/工具能力交给 agent'的项目，将在 30 天内被至少一个主流 agent 框架（LangChain、LlamaIndex、AutoGen 等）在官方文档或示例中引用或集成。 | community | 0.40 | 30 天 | 2026-12-27 | 截至到期日，在上述任一主流 agent 框架的官方文档、示例仓库或 release notes 中，出现对 CLI-Anything 或 superpowers 的明确引用/集成说明；若无则算落空。 | `it_1f28a16c9fe19cbe` `it_f859b2d15e1457f4` |
| firecrawl/firecrawl 在 30 天内将发布一个明确面向 agent 记忆/上下文持久化的新功能或子模块（如 crawl 结果直接写入可复用记忆存储）。 | capability | 0.35 | 30 天 | 2026-12-27 | 截至到期日，firecrawl 官方仓库 release 或文档中出现明确标注为 agent memory / context persistence 相关的新功能或子模块；若无则算落空。 | `it_8d57cc2cadedeb4f` `it_19dd4641586dbe86` |

### 证据条目对照（人工核验用）

- `it_8e49016f829cbdac` → Notion's official MCP inject hidden upsell instructions into agent context
- `it_f859b2d15e1457f4` → obra/superpowers
- `it_f09a3afb4ff397a9` → mvanhorn/last30days-skill
- `it_244a3e8cb4f170fa` → OpenAI cuts GPT-6.2 usage: Astra hits limits 40% faster, Sol 25% faster
- `it_536be0c2a1d62b85` → Top-cited AI scientists at four US companies compared
- `it_1d45997e4997625f` → AMD-specific fork of llama.cpp
- `it_ed75bf498e47451e` → jingyaogong/minimind
- `it_1f28a16c9fe19cbe` → HKUDS/CLI-Anything
- `it_f859b2d15e1457f4` → obra/superpowers
- `it_8d57cc2cadedeb4f` → firecrawl/firecrawl
- `it_19dd4641586dbe86` → AI made self-hosting fun again

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-27T01:52:37.589925+00:00_
