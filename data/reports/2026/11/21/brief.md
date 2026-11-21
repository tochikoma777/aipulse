# 🔭 AI 脉搏日报 · 2026-11-21

> 🕐 生成 2026-11-21 08:08（Asia/Shanghai） · 🤖 模式 hybrid（仅主编点评） · 📊 165 条 / 0 主题
> ⏱ 覆盖窗口：2026-11-20T08:06+08:00 → 2026-11-21T08:07+08:00（约 24.0 小时）

## ⚡ 今日头条

### 黎曼猜想同日出现「AI 版」与「纯人类版」两份证明，AI 数学叙事第一次被人类同行当场对质

🔗 来源：RSS · [AI claimed a solution to the 167-year-old Riemann hypothesis — and a human did, too](https://techcrunch.com/2026/11/20/ai-claimed-a-solution-to-the-167-year-old-riemann-hypothesis-and-a-human-did-too)
🏷️ `rss` · 🔥 热度 39.0

## 📋 总览

- 📄 **数学对质**：Anthropic 数学家 Levent Alpöge 称与 Claude 证明黎曼猜想并已形式化，同日另一条 RSS 指出 Brian Conrad 数月审阅的纯人类证明同样「看起来不错」，两条消息互为镜像，谁先被学界接受才是真信号。
- 🤖 **技能包泛滥**：GitHub 热榜被 Claude Code / agent skill 包占据——BugHunter 82 个技能、superpowers 方法论、last30days 跨平台调研、diagram-design 45 种图表，智能体生态正从「模型能力」转向「技能资产化」。
- 🔐 **供应链泄密**：研究者向 AI 服务链植入 200 万个数字金丝雀，发现敏感数据像筛子一样外泄，AI 中间层供应商是当前最被低估的隐私攻击面。
- 🏢 **算力政治**：特朗普威胁对境外建数据中心征「重税」，Meta 因 AI 数据中心排放创纪录而重审 2030 净零目标，算力的环境与地缘成本同时开始反噬叙事。
- 📉 **基础设施脆性**：Outlook 数日宕机、全国停飞、银行与 iCloud 接连失灵，「这周技术世界塌了」与 Google 搜索首页去掉搜索按钮形成对照：旧入口在退场，新入口还没证明自己可靠。

> **一句话**：今天最响的声音是 AI 攻下黎曼猜想，但真正决定走向的是同一天出现的人类证明、被技能包填满的热榜，以及算力与基础设施同时暴露的成本与脆性。

## ✍️ 主编点评

### 🎯 核心判断
今天最该记住的不是「AI 证明了黎曼猜想」，而是同一天出现了纯人类证明且已被同行审阅数月——AI 数学成果第一次在发布当天就被置于人类基准的对照之下，这比任何单次突破都更能校准我们对 AI 科研能力的判断。

### 🔍 交叉信号
开源热榜的 skill 包泛滥与 RSS 里「形式化验证是对抗 slop 的武器」指向同一件事：智能体产出越多，可验证性越贵；而 200 万金丝雀实验则从隐私侧印证，AI 中间层越多，可审计性越差。

### 🔄 反直觉
热度最高的黎曼猜想恰恰是今天最不该急着下结论的条目，而热度只有 39 的「金丝雀」实验才是已经发生、可复现、影响所有使用 AI API 团队的事实——热度与确定性在今天完全错位。

### ⚠️ 风险提醒
最大的盲点是「形式化」被当成免检章：Alpöge 称已形式化论证，但形式化只保证推理链自洽，不保证前提与建模正确；若社区把「已形式化」等同于「已证明」，会比任何一次 AI 幻觉都更难纠错。

## 🛠️ 开源项目

_热榜几乎被 agent skill 包与「让软件对智能体原生」的工具占据，开源竞争从模型转向可复用的技能与工作流资产。_

| 项目 | 热度 | ★ 总数 | 增量 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|---|---|
| [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | 88.0 🔥 · 连续 2 天 | 205249 | +1029 / 23h | firecrawl 是一个面向 AI agent 的知识基础设施，通过单一 API 提供搜索、抓取以及接入 550 多… | 把抓取、搜索和 550+ 数据源统一到一个 API，意味着 agent 的数据接入层从各家自建爬虫转向标准化采购，中小团队的数据工程成本被压到接近零。 | 数据获取正变成水电煤，护城河从『能抓到』转移到『抓得干净且合规』。 |
| [elementalsouls/Claude-BugHunter](https://github.com/elementalsouls/Claude-BugHunter) | 74.8 · 连续 2 天 | 14219 | +7850 / 121h | 一个 Claude Code 漏洞挖掘技能包，含 82 个 skills、15 个 slash 命令和 681 条已披… | 把 681 条已披露报告模式固化成技能包，让外部红队工作从个人经验变成可复制的检索库，攻击面知识扩散速度加快。 | 攻防知识的技能化不可避免，防守方必须假设对手已拥有同等清单。 |
| [XiaoYouChR/Ghost-Downloader-3](https://github.com/XiaoYouChR/Ghost-Downloader-3) | 71.7 · 连续 2 天 | 13681 | +979 / 23h | Ghost-Downloader-3 是一款开源的多功能下载器桌面应用 | 下载器把多协议、多源聚合进单一客户端，用户不再为不同站点装不同工具，边缘工具类软件的整合窗口正在关闭。 | 集大成者往往也是最后一款——这类工具的价值在于终结选择困难，而非创新。 |
| [obra/superpowers](https://github.com/obra/superpowers) | 69.3 · 连续 4 天 | 322825 | +3486 / 71h | obra/superpowers 是一套面向 AI agent 的技能框架与软件开发方法论 | 把 agent 技能封装成可复用的方法论框架，等于给『提示词工程』补上工程规范，团队协作时技能可以像依赖包一样被版本化和审查。 | 技能框架会像当年的 lint 规则一样成为标配，不采用的一方会在多人协作中先乱。 |
| [zhouxiaoka/autoclip](https://github.com/zhouxiaoka/autoclip) | 67.4 · 连续 2 天 | 12167 | +950 / 23h | AutoClip 是一个开源 AI 视频剪辑桌面工具，能把播客、访谈、课程等长视频一键剪成适配抖音、小红书、TikTo… | 把长视频拆条、字幕、封面、文案打包成桌面端一键流程，直接压缩了剪辑外包与内容代运营的生存空间，创作者的分发成本被摊到接近零。 | 开源桌面端而非 SaaS，是对平台抽成模式的正面绕行，我站这一边。 |
| [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) | 66.1 · 连续 5 天 | 71434 | +3270 / 94h | 一个 AI agent skill，可跨 Reddit、X、YouTube、HN、Polymarket 和网页检索任意… | 把跨平台检索与摘要合成打包成一个可复用技能，意味着 agent 的信息搜集从单站抓取转向多源交叉验证，直接压缩人工调研的时间成本。 | 多源聚合是 agent 技能里最实用的一类，但摘要的可靠性取决于源质量，别把它当事实核查工具。 |
| [toeverything/AFFiNE](https://github.com/toeverything/AFFiNE) | 59.0 · 连续 2 天 | 75787 | +623 / 23h | AFFiNE 是一个开源、隐私优先的知识库工具，把文档、白板与规划功能整合在一起 | 把文档、白板、规划合并进一个隐私优先的开源知识库，直接对 Notion+Miro 的组合收费模式施压，企业采购多了一个可自托管的替代项。 | 开源替代的胜负手不在功能对齐，而在迁移成本——这一步它还没证明。 |
| [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | 57.4 · 连续 2 天 | 69269 | +641 / 23h | 一套面向 Claude Code、Codex、GitHub Copilot、Cursor 等编程助手的编辑级图表设计规… | 把图表规范固化成 45 种自包含 HTML+SVG 模板喂给编码代理，等于给 AI 生成内容装上统一排版约束，输出从能看变成能发。 | 明确反对 Mermaid 那套默认样式，这种审美上的强硬是稀缺品。 |
| [mjmirza/app-store-compliance](https://github.com/mjmirza/app-store-compliance) | 57.0 · 连续 2 天 | 2722 | +887 / 23h | 一份开源的上架合规手册与提交前检查工具，收录 117 种 App Store 与 Google Play 拒审模式及修… | 把 117 条被拒模式和 95 个监管截止日做成预提交检查，等于把应用商店审核与合规风险前移到编码阶段，AI agent 也能直接调用。 | 合规检查下沉到开发工具链是必然，晚做的团队会用一次下架来补课。 |
| [jingyaogong/minimind](https://github.com/jingyaogong/minimind) | 56.3 · 连续 2 天 | 67676 | +1696 / 71h | minimind 是一个教学项目，演示如何在两小时内从零训练出一个 64M 参数的小型大语言模型。 | 两小时、单卡、64M 参数就能跑通从零预训练全流程，把大模型的门槛从实验室预算降到个人周末项目，教学与复现的价值远大于模型本身。 | 这是目前最有效的 LLM 祛魅工具，比任何科普文章都管用。 |

_另有 2 条未展示（完整列表见 daily.json）_

### 📈 增速榜（追踪中）

_今日未上榜、但 star 仍在快速增长的项目（仅取有合规增速窗口的快照；完整序列见 signals.json）_

- **dream-num/univer** · ★28906 · +4463 / 74h · 上次在榜 11-18
- **google-research/paper-orchestra** · ★4275 · +2695 / 47h · 上次在榜 11-19
- **GoogleChrome/modern-web-guidance-src** · ★7100 · +1158 / 24h · 上次在榜 11-16
- **affaan-m/ECC** · ★306500 · +991 / 24h · 上次在榜 11-19
- **ag-ui-protocol/ag-ui** · ★20001 · +2670 / 74h · 上次在榜 11-18

## 💬 社区舆论

_HN 上既有对推理芯片的「vibecoding」式调侃，也有 GitHub 删号求助与全周基础设施崩塌的集体焦虑。_

| 标题 | 热度 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|
| [Show HN: OpenComputer – an open source alternative to Devin](https://github.com/diggerhq/opencomputer) | 54.0 | OpenComputer 是 Devin 的开源替代品，一个可部署在自有 AWS、GCP、Azure 云账号中的云端编… | 把编码代理的运行框架和沙箱塞进同一台持久 VM 并部署在客户自有云账号，解决了企业最在意的代码出域问题，采购阻力从合规部门转移到工程部门。 | 自托管是编码代理进入企业的唯一现实路径，闭源 SaaS 会被这条路线挤压。 |
| [A few hours ago Google DeepMind created a math horizon repo](https://github.com/google-deepmind/math-horizon) | 65.2 | Google DeepMind 数小时前新建了一个名为 math horizon 的代码仓库。 | DeepMind 单独开一个数学方向仓库，通常意味着内部把数学能力当作独立产品线推进，外部研究者会据此推断其评测与数据策略的下一步。 | 只有仓库名没有内容，信息量接近于零，先别把它当成果来解读。 |
| [Inkling 2 Mini](https://thinkingmachines.ai/news/inkling-2-mini) | 87.8 🔥 | Hacker News 上出现一条名为 Inkling 2 Mini 的条目。 | 小尺寸模型迭代到 Mini 这一档，说明厂商在把推理成本往端侧和低配场景压，开发者选型时的默认基线会被再次拉低。 | 没有摘要就没有判断依据，这条目前只是名字，不值得占用注意力。 |
| [Vibecoding an inference chip](https://ankitg.me/blog/vibecoding-inference-chip) | 76.5 | 一篇讨论用 vibe coding 方式设计推理芯片的文章。 | 用自然语言驱动的方式设计推理芯片，把硬件定义周期从数月压到对话级迭代，受影响的是中小团队能否绕开 EDA 与流片经验壁垒。 | 方向诱人但验证成本极高，没有流片结果之前都只能算概念演示。 |
| [Help github just deleted me](https://nate.mecca1.net/posts/2026-11-20_help) | 42.8 | Hacker News 上一条关于 GitHub 账号被删除的求助帖。 | 账号被平台单方面删除且申诉通道失效，暴露的是开发者把代码托管、CI、身份全押在单一平台上的结构性风险，迁移成本才是真正的锁。 | 平台无解释封号且无有效申诉，这是治理缺陷，不是用户操作失误。 |

## 🏢 产业与新闻

_Google 搜索首页去掉搜索按钮、Meta 因 AI 排放重审净零、特朗普威胁数据中心出境税、Nvidia 余波未平，产业侧全是成本与权力的重新分配。_

| 标题 | 热度 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|
| [AI claimed a solution to the 167-year-old Riemann hypothesis — and a human did, too](https://techcrunch.com/2026/11/20/ai-claimed-a-solution-to-the-167-year-old-riemann-hypothesis-and-a-human-did-too) | 39.0 | 有 AI 宣称解决了 167 年历史的 Riemann hypothesis，同时也有数学家给出了人类解法。 | 同一难题上 AI 与人类方案同时出现，真正被检验的不是模型能力而是数学界的验证流程——谁来判断、多久能判，决定了这类宣称的可信度。 | 在同行评议完成前，AI 解题的新闻价值高于数学价值，别急着庆祝。 |
| [Quoting Ravi Vakil](https://simonwillison.net/2026/Nov/20/ravi-vakil) | 39.0 | Ravi Vakil 的一段引述，提到 Alessandro Masullo 提出的 Generalized Riem… | 当事人明确强调成果完全出自人类且已历经数月专家反馈，这条引述实际上是在为「AI 宣称」类新闻提供反证样本，把讨论拉回验证机制。 | 这条比上一条更值得读，它说明慢工评审仍然跑得赢热搜。 |
| [Anthropic mathematician claims to have solved prestigious Millennium Prize problem with Claude](https://www.theverge.com/ai-artificial-intelligence/1010051/anthropic-riemann-hypothesis-millennium-prize-problem) | 38.2 | Anthropic 数学家 Levent Alpöge 声称借助 Claude 证明了黎曼猜想这一千禧年大奖难题。 | 若黎曼猜想的证明成立，数学界最硬的公开难题之一将首次由人机协作攻下，AI 从辅助工具变成定理生产者，评审与优先权归属的规则随之被重写。 | 在同行评审与形式化验证通过前，这只能算一次高调宣称，但它的存在本身已把 AI 数学的可信度问题摆上台面。 |
| [Quoting Levent Alpöge](https://simonwillison.net/2026/Nov/20/levent-alpoge) | 38.1 | Levent Alpöge 自述与 Claude 合作找到了黎曼猜想的证明，并称方法可推广至广义黎曼猜想。 | 当事人自述把范围从黎曼猜想扩到广义乃至扩展黎曼猜想，并称已形式化论证，这意味着争议焦点从“是否真解出”转向“形式化内核能否被独立复核”。 | 把形式化作为证据链的一环是正确做法，但自我宣称不构成证明，社区必须逐行验核而非围观。 |
| [The War Against Slop and an Emerging Weapon to Fight it: Formal Verification](https://latent.space/p/formal-verification) | 39.0 | 文章讨论 AI 生成低质量代码「slop」泛滥，以及形式化验证作为应对手段的兴起。 | 当 AI 生成代码成为常态，形式验证从学术小众变成工程验收环节，团队的成本结构会从写代码转向写规格与证明，低质量产出的责任边界也随之清晰。 | 形式验证是当下对抗 AI 垃圾产出最实在的抓手，但它把门槛推给了规格撰写，别把它当成免费的质量保险。 |
| [The week everything fell apart](https://www.theverge.com/podcast/1038419/outage-outlook-ground-stop-tech-failure-vergecast) | 36.9 | 回顾一周内 Outlook 长时间宕机、全美航班停飞、银行与 iCloud 接连故障的集中事故。 | 邮件、航空、银行、云存储在同一周接连失守，说明关键基础设施的故障域已经耦合，单点事故会沿依赖链放大成社会级停摆。 | 把这一周读成“技术世界要崩”是情绪化叙事，但集中化依赖带来的系统性脆弱是真实的，冗余投入不能再被当成成本浪费。 |
| [Google rolls out new search homepage with AI chat history and no search button](https://arstechnica.com/ai/2026/11/googles-latest-search-page-redesign-drops-the-search-button-adds-ai-sidebar) | 39.0 | Google 正式上线新版搜索首页，加入 AI 对话历史并取消搜索按钮。 | 搜索首页去掉搜索按钮、加入 AI 对话历史，等于把入口从“查询框”改成“会话”，流量分发与广告位逻辑随之重构，靠关键词排名的内容方首当其冲。 | 这是把搜索降级为聊天机器人的附属功能，用户体验未必更好，但谷歌对入口控制权的加固是明确的。 |
| [Meta reconsiders 2030 net-zero goal amid record emissions from AI data centers](https://arstechnica.com/ai/2026/11/meta-reconsiders-2030-net-zero-goal-amid-record-emissions-from-ai-data-centers) | 39.0 | Meta 在最新可持续报告中因 AI 数据中心排放创新高，重新考虑 2030 年净零目标。 | AI 数据中心推高排放，使 Meta 公开松动 2030 净零承诺，气候目标在算力竞赛面前让位，其他大厂的承诺可信度随之被重新定价。 | 净零承诺一旦遇到算力扩张就退让，说明它从来不是约束而是公关，监管应把披露与核算做实。 |
| [Researcher plants 2m canaries into the AI supply chain. A privacy disaster surfaced.](https://arstechnica.com/security/2026/11/a-leaky-ai-supply-chain-is-exposing-secret-user-data-at-an-alarming-rate) | 39.0 | 研究者向 AI 服务链路植入 200 万个数字诱饵，追踪发现敏感数据在整个生态中被广泛泄露。 | 两百万个探针显示，请求在多层转售的 AI 服务链中被逐级泄露，敏感数据在用户看不见的中间商处外流，采购方对供应链的可见性几乎为零。 | AI 服务转售链的隐私黑洞是行业级丑闻，只靠服务条款无法解决，需要强制披露数据流向与下游处理方。 |
| [Daniel Ek backs AI researcher’s fusion power startup. Here’s what they’re building.](https://techcrunch.com/2026/11/20/daniel-ek-backs-ai-researchers-fusion-power-startup-heres-what-theyre-building) | 39.0 | Spotify 创始人 Daniel Ek 投资 AI 研究者创办的聚变能源初创公司 Europa Fusion。 | AI 研究者创办聚变公司并拿到知名创始人投资，反映资本正把 AI 的方法论与叙事迁移到能源硬科技，融资路径从实验室拨款转向明星天使。 | 跨界背书能带来资金与关注，但聚变靠的是工程与物理而非模型调参，别让 AI 光环替代技术里程碑。 |

_另有 3 条未展示（完整列表见 daily.json）_

## ⚔️ 矛盾点

1. 同一事件两种叙事：RSS 称 Anthropic 数学家 Levent Alpöge 与 Claude 证明黎曼猜想，另一条 RSS 引 Ravi Vakil 称 Alessandro Masullo 的证明「全是人类、没有 AI」且进展良好——两条都指向 GRH，谁是真证明、是否存在两个独立证明，数据本身无法判定。
2. Nvidia 条目一边说「罢免 CEO 黄仁勋后的余波」，一边说财报健康增长并停止对华销售 H200，管理层动荡与业务向好同时成立，叙事内部张力明显。
3. Google 搜索首页去掉搜索按钮、转向 AI 对话历史，与「这周技术世界塌了」的基础设施连环故障并列：入口在激进改造，可靠性却在倒退。

## 💎 被低估

- Researcher plants 2m canaries into the AI supply chain. A privacy disaster surfaced.
- The War Against Slop and an Emerging Weapon to Fight it: Formal Verification
- mjmirza/app-store-compliance：117 条拒审模式 + 95 个 EU AI Act/DSA/COPPA 截止日期
- jingyaogong/minimind：两小时从零训出 64M 大模型
- Chips can survive the space environment — can their financing?
- HKUDS/CLI-Anything：让所有软件对智能体原生

---

<sub>🤖 运行模式 hybrid（仅主编点评） · 📄 数据声明：仅存储标题、摘要与公开指标，均标注来源与原链接，不做全文转载。</sub>
