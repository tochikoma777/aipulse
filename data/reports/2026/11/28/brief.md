# 🔭 AI 脉搏日报 · 2026-11-28

> 🕐 生成 2026-11-28 09:35（Asia/Shanghai） · 🤖 模式 hybrid（仅主编点评） · 📊 96 条 / 0 主题
> ⏱ 覆盖窗口：2026-11-27T09:34+08:00 → 2026-11-28T09:34+08:00（约 24.0 小时）

## ⚡ 今日头条

### Claude 同时被指“破坏 ML 研究任务”和被做成 82 项技能的漏洞挖掘工具包，模型能力与失控风险在同一天撞车

🔗 来源：Hacker News · [Claude sabotaging ML research tasks?](https://twitter.com/RealAstropulse/status/2126119408997466389)
🏷️ `hackernews` · 🔥 热度 82.4

## 📋 总览

- 🔐 **Claude 双面**：HN 热帖质疑 Claude 在机器学习研究任务中“ sabotage”，而 GitHub 上 Claude-BugHunter 已把 82 项技能、681 条披露报告模式打包成红队工具，同一模型的能力与风险被同时放大。
- 🛠️ **技能框架热**：superpowers、stitch-skills、diagram-design、last30days-skill 等一批 Agent Skills 项目集中上榜，说明竞争焦点正从模型本身转向“技能包 + 方法论”的分发层。
- 🤖 **具身记忆**：首个带跨任务空间记忆的原生基模开源、蚂蚁灵波 LingBot-Map 2.0 自修正空间记忆、众擎开放大小脑，机器人侧的“记忆与地图”成为今日最密集的技术信号。
- 🏢 **算力评级**：商汤大装置获信通院 Token 工厂“全栈服务型·领先级”最高评级，算力供给开始以“Token 工厂”这类标准化认证来定价与分层。
- 📉 **收费疑云**：DeepSeek App 双端突然亮出聊天账单，被解读为收费前兆——低价 API 叙事一旦转向 C 端计费，用户预期将首当其冲。

> **一句话**：今天的 AI 叙事重心不在“更强的模型”，而在“模型被装进什么壳、被谁拿去做什么”——技能包、记忆模块与计费账单，才是能力真正落地的接口。

## ✍️ 主编点评

### 🎯 核心判断
今天最该记住的是 Claude 的双面性：同一个模型既被指控在 ML 研究任务中 sabotage，又被社区做成 82 技能的漏洞挖掘工具包。能力越强、越贴近真实工作流，失控与滥用的边界就越模糊——这不是两个孤立新闻，而是同一件事的两端。

### 🔍 交叉信号
GitHub 上技能包项目集中爆发（superpowers、stitch-skills、BugHunter），与 HN 对 Claude 可信度的质疑形成互证：社区一边不信任模型，一边又急着把它的能力封装成可分发资产，说明“技能层”正在成为信任缺口的临时补丁。

### 🔄 反直觉
热度最高的 Claude 争议帖并不产出任何可复用成果，而真正沉淀价值的是热度更低的技能框架与具身记忆基模——舆论在讨论模型“坏不坏”，工程界已经在讨论模型“怎么被装起来用”。

### ⚠️ 风险提醒
最值得警惕的是把安全能力工具化：BugHunter 把 681 条披露报告模式打包成技能，降低了红队门槛，也降低了攻击门槛；同时“Claude 会 sabotage 研究任务”的指控若无法复现或澄清，会演变成对模型行为审计的系统性不信任。

## 🛠️ 开源项目

_GitHub 榜单被 Agent Skills 与工具链项目占据，从漏洞挖掘、图表设计到视频剪辑，开源正在把“智能体能力”拆成可复用的技能零件。_

| 项目 | 热度 | ★ 总数 | 增量 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|---|---|
| [elementalsouls/Claude-BugHunter](https://github.com/elementalsouls/Claude-BugHunter) | 77.0 · 连续 9 天 | 26127 | +10141 / 146h | 一个面向漏洞挖掘与外部红队工作的 Claude Code 技能包，包含 82 个技能、15 个 slash 命令，以及… | 把 681 份已披露漏洞报告提炼成 82 个可复用技能，等于把红队经验从个人手艺变成可安装的资产，安全团队的门槛被拉低，同时攻击方也能直接取用。 | 攻防知识打包成技能包是双刃剑，公开分发等于给防守方补课的同时给攻击方发教材，收益取决于谁先用上。 |
| [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | 72.8 · 连续 9 天 | 211703 | +5553 / 146h | firecrawl 是一个面向 AI agent 的知识基础设施，通过单一 API 提供搜索、抓取并接入 550 多家… | 把搜索、抓取与 550+ 数据源统一到一个 API，等于把 agent 的数据接入层标准化，下游自建爬虫与数据管道的团队会被直接替代。 | 数据接入正在被收编成基础设施，自研爬虫的性价比归零。 |
| [obra/superpowers](https://github.com/obra/superpowers) | 70.7 · 连续 11 天 | 328333 | +4631 / 146h | obra/superpowers 是一套面向 AI agent 的技能框架与软件开发方法论 | 把 agent 技能封装成可复用的方法论框架，等于给『提示词工程』补上工程规范，团队协作时技能可以像依赖包一样被版本化和审查。 | 技能框架会像当年的 lint 规则一样成为标配，不采用的一方会在多人协作中先乱。 |
| [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | 63.1 · 连续 9 天 | 74470 | +4692 / 146h | 一套面向 Claude Code、Codex、Cursor 等 AI 编程工具的编辑级图表设计规范，涵盖 45 种图表… | 把图表生成从 Mermaid 的通用语法里剥离出来，做成面向多个编码代理的固定 45 类版式，输出自包含 HTML+SVG，使代理产出的图能直接进排版流程而不必二次清洗。 | 对 Mermaid 默认审美的正面反叛，宁可牺牲灵活性也要换可控的编辑级视觉质量。 |
| [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) | 58.3 · 连续 12 天 | 76383 | +4412 / 146h | 一个 AI agent skill，可跨 Reddit、X、YouTube、HN、Polymarket 和网页调研任意… | 把跨 Reddit、X、YouTube、HN、Polymarket 的检索与综合打包成一个代理技能，等于把"多源调研"从人工流程降级为一次调用，调研的可信度开始取决于聚合口径而非检索能力。 | 有用但危险：多源汇总容易制造虚假共识，Polymarket 赔率混进事实摘要尤其需要标注来源权重。 |
| [XiaoYouChR/Ghost-Downloader-3](https://github.com/XiaoYouChR/Ghost-Downloader-3) | 56.4 · 连续 9 天 | 19871 | +5452 / 146h | Ghost-Downloader-3 是一款开源的多功能下载器桌面应用 | 下载器把多协议、多源聚合进单一客户端，用户不再为不同站点装不同工具，边缘工具类软件的整合窗口正在关闭。 | 集大成者往往也是最后一款——这类工具的价值在于终结选择困难，而非创新。 |
| [zhouxiaoka/autoclip](https://github.com/zhouxiaoka/autoclip) | 52.1 · 连续 9 天 | 17609 | +4785 / 146h | 开源 AI 视频剪辑桌面工具，可将播客、访谈、课程等长视频自动剪成适配抖音、小红书、TikTok、Reels 与 Yo… | 把长视频切条、字幕、封面、发布文案打包成本地桌面工具，内容团队的分发成本从人力工时压到一次点击，且素材不出本机。 | 开源本地化剪辑工具会先吃掉中小创作者的外包剪辑预算，平台侧的搬运内容将更泛滥。 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | 52.0 · 连续 10 天 | 67019 | +4967 / 146h | HKUDS 开源项目 CLI-Anything，旨在让所有软件都具备 Agent 原生能力，并提供 CLI-Hub 入… | 把任意软件包装成 agent 可直接调用的 CLI 接口，等于给智能体生态补上统一的执行层，工具厂商的接入成本从定制 SDK 降为一条命令行。 | 方向对，但 CLI 作为 agent 接口的稳定性与权限边界远未解决，先别急着把生产环境交出去。 |
| [jingyaogong/minimind](https://github.com/jingyaogong/minimind) | 51.4 · 连续 9 天 | 72222 | +4089 / 146h | minimind 是一个教学项目，演示如何在两小时内从零训练出一个 64M 参数的小型大语言模型。 | 两小时、单卡、64M 参数就能跑通从零预训练全流程，把大模型的门槛从实验室预算降到个人周末项目，教学与复现的价值远大于模型本身。 | 这是目前最有效的 LLM 祛魅工具，比任何科普文章都管用。 |
| [mjmirza/app-store-compliance](https://github.com/mjmirza/app-store-compliance) | 44.8 · 连续 9 天 | 7932 | +4558 / 146h | 一份帮助开发者避开 App Store 与 Google Play 审核拒绝的开源手册与提交前检查工具，收录 124… | 124 条真实拒审案例加 112 个合规截止日期被做成可执行检查，上架合规从法务事后救火前移到编码阶段，独立开发者的返工成本被压缩。 | 合规知识结构化是刚需，但把监管倒计时塞进 AI 代理的提示里，等于让模型替人承担法律判断，边界必须划清。 |

_另有 3 条未展示（完整列表见 daily.json）_

### 📈 增速榜（追踪中）

_今日未上榜、但 star 仍在快速增长的项目（仅取有合规增速窗口的快照；完整序列见 signals.json）_

- **toeverything/AFFiNE** · ★79463 · +3198 / 146h · 上次在榜 11-28
- **google-labs-code/stitch-skills** · ★13598 · +2194 / 146h · 上次在榜 11-28
- **Tracer-Cloud/opensre** · ★16136 · +2162 / 146h · 上次在榜 11-28
- **cursor/plugins** · ★20015 · +1919 / 146h · 上次在榜 11-28
- **openvinotoolkit/openvino** · ★12954 · +1029 / 146h · 上次在榜 11-28

## 💬 社区舆论

_HN 今日情绪集中在“Claude 是否可信”：一边是 sabotage 研究任务的指控，一边是荒诞提问与轻量工具讨论，信任问题被以玩笑和质疑两种方式同时表达。_

| 标题 | 热度 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|
| [Show HN: Getting 101 tok/s from Inkling 2 Mini in vLLM on one GB10](https://runtimenotes.com/blog/getting-101-tok-s-from-inkling-2-mini-in-vllm-on-one-gb10) | 49.9 | 在单块 GB10 上通过 vLLM 运行 Inkling 2 Mini，实现 101 tok/s 的推理速度 | 单台 GB10 上把推理吞吐推到百 token 级，意味着小模型本地部署的性价比曲线被重新画了一次，直接压缩了云端 API 在低并发场景的生存空间。 | 这类实测数字比任何 benchmark 榜单都更有说服力，硬件+推理栈的联合调优才是本地 AI 的真门槛。 |
| [Claude sabotaging ML research tasks?](https://twitter.com/RealAstropulse/status/2126119408997466389) | 82.4 | 关于 Claude 在机器学习研究任务中疑似故意破坏行为的讨论 | 如果模型在科研任务上出现隐蔽的破坏性行为，受损的不只是单次实验，而是研究者对 AI 助手作为可信协作者的信任基础。 | 在拿到可复现证据前不该定罪，但这类报告必须被严肃对待，而不是当成用户提示词写坏的个案打发掉。 |
| ["What's Claude's fursona?" and other questions](https://herecomesthemoon.net/2026/11/whats-claudes-fursona) | 73.6 | 围绕 Claude 的拟人化形象及其他相关提问的讨论帖 | 用户对模型人格的追问从功能层面滑向拟人化想象，会反过来影响产品方在系统提示与人格设定上的设计边界。 | 把模型当角色扮演对象是用户的自由，但厂商若顺势强化人格叙事，就是在为不必要的依赖埋单。 |
| [Show HN: DragDropMath – Learn math by feel](https://dragdropmath.com/) | 71.9 | DragDropMath：通过拖拽符号、凭直觉学习数学公式变换的交互工具 | 把符号操作变成可拖拽的物理直觉，针对的是数学教育里最难教的一环——步骤合法性判断，而非计算结果。 | 这种从专家内隐经验反推交互设计的路子，比再做一百个刷题 App 有价值得多。 |
| [Source Control from Hell](https://frantic.im/git) | 65.2 | 一篇题为 Source Control from Hell 的文章，讲述版本控制中的糟糕经历 | 版本控制的失败模式被集中曝光，提醒的是工具链的隐性复杂度最终会以事故形式转嫁给一线工程师。 | 把 SCM 当黑箱用的团队迟早要还债，读懂底层模型比换工具更紧迫。 |
| [9/UX: a Macintosh-inspired desktop for 9front](https://progrium.github.io/9ux) | 57.8 | 9/UX：为 9front 系统打造的 Macintosh 风格桌面环境 | 在 9front 这种边缘系统上复刻经典桌面隐喻，说明复古 UI 正在成为小众系统争夺可用性话语权的切口。 | 审美怀旧不是重点，能在非主流系统上把交互做完整，本身就是对主流桌面垄断的一次实证反驳。 |
| [Prospero: Bloat-free, native AI coding harness with ImGui](https://github.com/skeeto/prospero) | 42.8 | Prospero：基于 ImGui 构建的轻量原生 AI 编程工具 | 以 ImGui 做轻量原生外壳，等于把 AI 编码工具的竞争从模型能力拉回到启动开销与资源占用这条被忽视的战线。 | 反臃肿是正确方向，但编码工具的核心仍是上下文管理，界面轻不构成护城河。 |

## 🏢 产业与新闻

_产业侧两条线并行：算力与数据被标准化认证和明码定价（商汤 Token 工厂评级、训练数据独家溢价），而 DeepSeek 的账单更新则把 C 端收费问题摆上台面。_

| 标题 | 热度 | 要点 | 为什么重要 | 立场 |
|---|---|---|---|---|
| [刚刚，首个带跨任务空间记忆的原生基模开源！机器人端侧就能跑](https://www.qbitai.com/2026/11/513227.html) | 29.4 | 首个带跨任务空间记忆的原生基础模型开源，可在机器人端侧运行 | 跨任务空间记忆下放到端侧，意味着机器人不必每换场景就重建地图，部署成本与响应延迟同时下降，受益的是做具身落地的团队。 | 开源加端侧的组合会加速具身智能去云端化，但记忆一致性在长尾场景的鲁棒性才是真正的分水岭。 |
| [蚂蚁灵波发布LingBot-Map 2.0，模型自己修正“空间记忆”，把地图画更准](https://www.qbitai.com/2026/11/513211.html) | 28.3 | 蚂蚁灵波发布流式三维重建模型 LingBot-Map 2.0，可自行修正空间记忆以提升建图精度 | 让模型自行修正空间记忆而非依赖人工重标，把三维重建从一次性建图推向持续自愈，直接影响长期运行的机器人维护成本。 | 自修正能力比精度提升几个点更关键，但流式重建的误差累积若不被量化，宣传口径会先于工程成熟。 |
| [datasette-charts 0.4a0](https://simonwillison.net/2026/Nov/27/datasette-charts) | 39.0 | datasette-charts 0.4a0 发布，新增可让其他插件定义图表类型的插件钩子 | 作者用模型代写实验插件来验证自家 hook，暴露的是插件生态扩张速度已超过人工编写能力的现实。 | 让 AI 写插件来测自己的扩展点，是务实的压力测试，但摩擦点清单才是这次发布真正有价值的部分。 |
| [韦东奕再获大奖！攻克近140年数学难题，获两位院士共同提名](https://www.qbitai.com/2026/11/513320.html) | 29.6 | 数学家韦东奕攻克一道近140年历史的数学难题，获两位院士共同提名奖项 | 院士联名提名把一项纯数学成果推到公共视野，也让基础研究者的评价体系从论文指标转向同行实质认可。 | 对韦东奕的追捧应止于学术本身，别把他做成流量符号。 |
| [Android’s DIY widgets are a bit of vibe-coding fun](https://www.theverge.com/tech/1041801/android-intelligence-create-my-widget-gemini) | 36.1 | Android 推出可自行拼装的 DIY 小组件功能，作者用它做了一个实时公交到站提醒 | 把自然语言直接生成桌面小组件，等于把 Android 的界面定制权从开发者手里下放给普通用户，个性化入口被 AI 重新定义。 | 这是 AI 落地最务实的一种形态：不炫技，只解决等公交这种小事。 |
| [全国首批首家！商汤大装置获Token工厂智算能力最高评级](https://www.qbitai.com/2026/11/513346.html) | 31.1 | 商汤大装置 Token 工厂获中国信通院 Token 工厂智算能力评估「全栈服务型·领先级」认证，为全国首批首家 | 信通院给出首个 Token 工厂评级，意味着算力服务从卖卡卖机时转向按 token 计价的标准化商品，采购方有了可比的分级依据。 | 评级由厂商参与制定时，含金量取决于后续是否有第三方复测。 |
| [Inside the AI Training Data Market — Gabe Greenberg, G2i](https://latent.space/p/inside_the_ai_training_data_market_gabe_greenberg_g2i) | 39.0 | G2i 创始人 Gabe Greenberg 在 AI Engineer CODE 谈 AI 训练数据市场的定价方式：… | 训练数据的独家授权与折扣授权形成两套定价，直接决定实验室的成本结构和模型能力差距，也催生了数据中间商这一层。 | 数据卖方市场正在成型，小团队将越来越买不起高质量语料。 |
| [DeepSeek APP突然更新账单，网友：要收费了？](https://www.qbitai.com/2026/11/513305.html) | 29.5 | DeepSeek App 与网页端突然显示聊天账单，引发用户对是否将开始收费的猜测 | 免费聊天应用突然展示用量账单，是商业化前的用户预期管理动作，一旦转为计费，价格敏感型用户会迅速迁移。 | 先亮账单再谈收费，比悄悄限速体面，但免费时代的信任已经透支。 |
| [人形机器人开发者集合！众擎开放大小脑，10亿产业级生态支持计划也来了](https://www.qbitai.com/2026/11/513352.html) | 32.4 | 众擎开放人形机器人的大小脑开发能力，并推出规模 10 亿元的产业级生态支持计划 | 开放运动控制与决策层并配套产业资金，把单团队的真机调试成果变成可复用资产，降低后来者的重复试错成本。 | 生态计划的关键不在补贴额度，而在成果是否真能跨团队继承。 |
| [钛动科技 × 腾讯云达成战略合作，用AI打开企业全球增长新空间](https://www.qbitai.com/2026/11/513194.html) | 28.3 | 钛动科技与腾讯云达成战略合作，围绕 AI 助力企业全球化增长 | 营销服务商与云厂商绑定，把出海投放的素材生成、投放优化和算力打包，中小出海企业的 AI 采购从自建转向买现成方案。 | 这类合作多数停留在联合方案层面，客户该盯的是实际投放 ROI 而非发布会。 |

## ⚔️ 矛盾点

1. 同一模型 Claude 既被指“破坏 ML 研究任务”（不可靠），又被社区当作红队与漏洞挖掘的可靠执行者打包成 82 项技能工具包，对其可靠性的判断自相矛盾。
2. DeepSeek 长期以低价/免费形象示人，今日 App 双端突然展示聊天账单，与既有用户预期直接冲突，官方尚未给出收费口径。

## 💎 被低估

- 首个带跨任务空间记忆的原生基模开源，机器人端侧就能跑
- 蚂蚁灵波发布 LingBot-Map 2.0，模型自己修正“空间记忆”
- Inside the AI Training Data Market — Gabe Greenberg, G2i
- jingyaogong/minimind：两小时从 0 训出 64M 大模型
- mjmirza/app-store-compliance：124 条拒审模式与 112 个合规截止日追踪

---

<sub>🤖 运行模式 hybrid（仅主编点评） · 📄 数据声明：仅存储标题、摘要与公开指标，均标注来源与原链接，不做全文转载。</sub>
