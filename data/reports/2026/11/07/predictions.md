## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| 在 30 天窗口内，GitHub 上新创建、名称或描述含 "skill"/"skills" 且明确定位为 AI agent 能力包的公开仓库新增 ≥5 个，其中至少 1 个 star 数达到 1000。 | community | 0.65 | 30 天 | 2026-12-07 | 截至到期日，用 GitHub 搜索 `skills agent created:>{窗口起始日}` 并按 star 排序统计：若满足「名称或描述含 skill/skills 且被 README 描述为 agent 能力包」的仓库 ≥5 个且最高 star ≥1000，算命中；若新增 <5 个，或最高 star <1000，算落空。 | `it_77f9ddd43bbeeb71` `it_5d1070aaeb2b84b3` `it_81446f2462dee9e2` |
| 在 30 天窗口内，GitHub 上新创建的 browser-use / computer-use 类 agent 开源项目中出现 ≥3 个 star 达到 500 的仓库。 | product | 0.70 | 30 天 | 2026-12-07 | 截至到期日，用 GitHub 搜索 `browser agent`、`computer use`、`browser-use` 且 `created:>{窗口起始日}`，统计定位为「让模型驱动浏览器/桌面操作」的仓库：≥3 个仓库 star ≥500 算命中；<3 个算落空。已存在的项目复刻不计入。 | `it_a4e85f0863890b24` `it_f7fc24d300640e30` `it_eb4a2c6a72538e9a` |
| 在 90 天窗口内，OpenAI、Anthropic、Google、Mistral 中至少一家在官方 API 文档中上线「按置信度或失败自动升级到更强模型」的原生路由参数或端点。 | capability | 0.50 | 90 天 | 2027-02-05 | 截至到期日，检查上述四家官方 API 文档与 changelog：若出现官方支持的「小模型先答、失败/低置信时自动回退或升级到更强模型」的参数、端点或托管路由功能（非第三方框架实现），算命中；四家均无官方支持，仅有社区库实现，算落空。 | `it_ef2a83f7f3a44d74` `it_a4f95935e39bb782` |
| 在 90 天窗口内，OpenCompass、HELM、LiveBench、SWE-bench 中至少一个公开榜单发布使用 <50% 抽样子集完成的官方评测结果，并在说明中标注子集抽样方法。 | research | 0.40 | 90 天 | 2027-02-05 | 截至到期日，检查上述四个榜单的官方发布说明或博客：若存在一次官方评测明确使用不超过全量 50% 的抽样子集并标注抽样/压缩方法，算命中；若全部仍使用全量或固定子集且未标注抽样方法，算落空。 | `it_a4f95935e39bb782` `it_ef2a83f7f3a44d74` |
| 在 90 天窗口内，至少 3 家头部 AI 公司（Perplexity 计入其中）上线面向企业工作场景的 agent 产品公开定价页，按席位或按任务计费。 | business | 0.55 | 90 天 | 2027-02-05 | 截至到期日，统计 OpenAI、Anthropic、Google、Perplexity、Microsoft 等公司官网：若 ≥3 家存在独立产品页且含公开价格（美元/席位/月 或 美元/任务），算命中；若 <3 家（含仅 waitlist、仅联系销售无公开价格），算落空。 | `it_eb4a2c6a72538e9a` `it_a4e85f0863890b24` |

### 证据条目对照（人工核验用）

- `it_77f9ddd43bbeeb71` → cloudflare/security-audit-skill
- `it_5d1070aaeb2b84b3` → google/skills
- `it_81446f2462dee9e2` → mattpocock/skills
- `it_a4e85f0863890b24` → vercel-labs/agent-desktop
- `it_f7fc24d300640e30` → D4Vinci/Scrapling
- `it_eb4a2c6a72538e9a` → Perplexity launches AI agents for work
- `it_ef2a83f7f3a44d74` → A Jev that can ask Opus for help gives Opus accuracy at 4x lower cost
- `it_a4f95935e39bb782` → Random Is Almost Enough? Stable and Low-Cost Benchmark Compression via BestRand
- `it_a4f95935e39bb782` → Random Is Almost Enough? Stable and Low-Cost Benchmark Compression via BestRand
- `it_ef2a83f7f3a44d74` → A Jev that can ask Opus for help gives Opus accuracy at 4x lower cost
- `it_eb4a2c6a72538e9a` → Perplexity launches AI agents for work
- `it_a4e85f0863890b24` → vercel-labs/agent-desktop

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-07T04:31:48.774019+00:00_
