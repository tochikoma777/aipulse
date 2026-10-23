## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| anthropics/knowledge-work-plugins 仓库的 GitHub star 数在 30 天内达到 1000 以上。 | community | 0.55 | 30 天 | 2026-11-22 | 截至到期日，在 github.com/anthropics/knowledge-work-plugins 页面读取 star 计数：≥1000 判为命中，<1000 判为落空；若仓库被删除、转私有或改名为不可访问状态，同样判为落空。 | `it_c9cdc26758b48a34` `it_a7519c6ce55f34ab` |
| 30 天内 linux-stable 分支会合入至少一个当日在公开邮件列表被误发的 Linux 内核漏洞的修复补丁，并随稳定版内核发布。 | policy | 0.70 | 30 天 | 2026-11-22 | 截至到期日，将 30 天前与到期日的 linux-stable 分支提交对比，或查阅 kernel.org 的 stable release 公告：若至少有一个补丁/公告条目对应这批被误发漏洞（含其 CVE 编号或邮件列表讨论中标注的函数、子系统）判为命中；若 30 天内发布的所有稳定版均不含相关修复，判为落空。 | `it_72972368be1f96c8` `it_77f9ddd43bbeeb71` |
| 90 天内 GitHub 上至少出现一个以自然语言动作或骨架动作为条件的 latent world model 开源实现仓库（非仅论文页面），且其 star 数达到 300 以上。 | research | 0.45 | 90 天 | 2027-01-21 | 截至到期日，在 GitHub 以 latent world model 结合 language action / skeleton action 检索，若存在 ≥1 个包含可运行训练或推理代码的仓库且 star ≥300 判为命中；若只有论文 arXiv 页面、项目主页或 star <300 的实现，判为落空。 | `it_463277c6c46271fe` `it_c8222c7454357e3f` |
| 90 天内 vLLM、SGLang、TensorRT-LLM、llama.cpp 中至少一个的正式 release notes 出现跨层专家共享（cross-layer expert sharing）方向的 MoE 推理支持条目。 | capability | 0.30 | 90 天 | 2027-01-21 | 截至到期日，逐一检查上述四个项目在 90 天内的 GitHub Releases 说明：若任一项目的 release notes 出现 cross-layer / layer-shared expert、专家跨层复用或等价的 MoE 权重共享推理支持条目判为命中；若四个项目均无相关条目判为落空。 | `it_98169d606489bb04` `it_8ea6ea906fb17117` |
| 90 天内 Perplexity、Google Gemini Deep Research、OpenAI Deep Research 中至少一个上线以视频为输入源、直接产出研究报告的功能。 | product | 0.35 | 90 天 | 2027-01-21 | 截至到期日，检查三家产品的官方功能页与更新日志：若任一产品的深度研究功能明确支持上传或引用视频链接并输出结构化研究报告（而非仅视频摘要或字幕问答）判为命中；若三家均只提供文本/网页输入的深度研究判为落空。 | `it_41ec37365e67af16` `it_593011f7fe1bce84` |

### 证据条目对照（人工核验用）

- `it_c9cdc26758b48a34` → anthropics/knowledge-work-plugins
- `it_a7519c6ce55f34ab` → luongnv89/claude-howto
- `it_72972368be1f96c8` → Several Linux kernel vulnerabilities accidentally posted to public mailing list
- `it_77f9ddd43bbeeb71` → cloudflare/security-audit-skill
- `it_463277c6c46271fe` → LaLa-World: Scaling Latent World Models with Natural Language Actions
- `it_c8222c7454357e3f` → Skeleton-Grounded Latent Action Model for Robot World Models
- `it_98169d606489bb04` → Meta Expert: Cross-Layer Expert Sharing for Storage- and Retrieval-Efficient MoE
- `it_8ea6ea906fb17117` → Policy-Mask: Budget-Aware Adaptation of Diffusion Features to Discriminative Tasks
- `it_41ec37365e67af16` → Beyond Watching and Searching: Benchmarking Agents for Video-centered Deep Research Reports
- `it_593011f7fe1bce84` → Reading, Writing, Sharing, and Interacting with the World through Video

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-10-23T03:16:50.725738+00:00_
