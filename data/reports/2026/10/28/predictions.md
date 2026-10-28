## 🔮 今日新生成的预言

本次共生成 **5** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| 截至 30 天后，arXiv 上提交日期落在该窗口内、同时命中「world model」与「backtracking 或 policy improvement」的新论文达到 5 篇及以上。 | research | 0.70 | 30 天 | 2026-11-27 | 以 arXiv 全站检索式 all:"world model" AND (all:"backtracking" OR all:"policy improvement") 检索，按提交日期（v1 提交时间）筛选出位于窗口内的论文，人工去重后计数；≥5 篇为命中，≤4 篇为落空。仅统计标题或摘要明确涉及用世界模型做策略改进/经验回溯的论文。 | `it_7c5f24ff8abc41e4` `it_67efa096f7508ca3` `it_d350ced903bfdd10` `it_28d5719e052bb016` |
| Liquid AI 在 30 天内会在 Hugging Face 上发布 LFM3 系列的开放权重 checkpoint，且模型卡明确声明支持至少两种输入模态（文本加图像或音频之一）。 | product | 0.70 | 30 天 | 2026-11-27 | 截至到期日，检查 huggingface.co 上 LiquidAI 组织下的模型列表：若出现名称含 LFM3 的仓库、权重可公开下载（非 gated 或申请即通过亦可计入），且模型卡 README 中声明支持 ≥2 种模态输入，则为命中；若 30 天内仅有博客/技术报告而无 HF 开放权重，或仅有纯文本单模态 checkpoint，则为落空。 | `it_767a7db22edd6680` `it_4cd4ee44e5c10169` |
| HKUDS/DeepTutor 仓库在 30 天内 GitHub star 数达到 1000 及以上。 | community | 0.60 | 30 天 | 2026-11-27 | 到期日读取 github.com/HKUDS/DeepTutor 页面显示的 star 计数：≥1000 为命中，<1000 为落空；若仓库在窗口内被删除、转为私有或改名导致无法访问，则记为落空。 | `it_9780abeb5fce378d` `it_62b1fcdba263ec2d` |
| Anthropic 在 90 天内会通过官方渠道（anthropic.com 博客/新闻页或法院公开文件）就「训练数据包含盗版/非法获取书籍」的指控作出具名公开回应。 | policy | 0.60 | 90 天 | 2027-01-26 | 截至到期日，在 anthropic.com 的官方博客/新闻页检索，或在美国法院公开案卷（PACER 或 CourtListener）中检索涉及 Anthropic 与书籍版权/盗版训练数据的案件文书；出现至少一份由 Anthropic 署名或由其代理律师提交、明确回应训练数据获取合法性的公开文本即为命中；若 90 天内仅有无署名媒体转述或第三方评论，则为落空。 | `it_a4c44e96b0a94df5` `it_470e7f2ce2bd99e1` |
| 90 天内，arXiv 上会出现 3 篇及以上以「智能体长期记忆中的习惯/弱证据归纳」为标题或摘要核心贡献的新论文。 | research | 0.50 | 90 天 | 2027-01-26 | 以 arXiv 检索式 (all:"agent memory" AND (all:"habit" OR all:"longitudinal" OR all:"weak evidence")) 检索，筛选 v1 提交日期在窗口内的论文，人工确认其核心贡献为从长期弱证据中归纳用户/智能体行为模式，去重后 ≥3 篇为命中，≤2 篇为落空；仅把长期记忆作为工程手段而非研究贡献的论文不计入。 | `it_3917f884420d4288` `it_af76b0f8d8982cc5` |

### 证据条目对照（人工核验用）

- `it_7c5f24ff8abc41e4` → Rollback: Experience Backtracking in World Models for Policy Improvement
- `it_67efa096f7508ca3` → ThinkWorld: World Imagination Reinforces Chain-of-Dynamics Reasoning
- `it_d350ced903bfdd10` → Hy-Nomas: Towards Free-form Interactive World Generation
- `it_28d5719e052bb016` → ChronoReplay: One Answer Interface Is Not Enough for Streaming Spatial Intelligence
- `it_767a7db22edd6680` → Introducing LFM3: Every Modality for Specialized Intelligence
- `it_4cd4ee44e5c10169` → There are now 5 inference providers for abliterated DeepSeek
- `it_9780abeb5fce378d` → HKUDS/DeepTutor
- `it_62b1fcdba263ec2d` → Survival LLM: AI assistant and emergency library that runs on your own computer
- `it_a4c44e96b0a94df5` → Anthropic trained Claude on illegally obtained Stanford professors' books
- `it_470e7f2ce2bd99e1` → Is my data used for model training?
- `it_3917f884420d4288` → HABIT-Bench: Evaluating Habit Induction from Longitudinal Weak Evidence in Agent Memory
- `it_af76b0f8d8982cc5` → RSI Arena: Towards Recursive Self-Improvement with Human Feedback

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-10-28T03:52:50.386633+00:00_
