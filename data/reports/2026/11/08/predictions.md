## 🔮 今日新生成的预言

本次共生成 **4** 条可证伪预言：

| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |
|---|---|---|---|---|---|---|
| 到 30 天后，GitHub 上由大型组织官方账号发布、仓库名含 "skills" 且用于向 AI 编码智能体提供可插拔能力的仓库总数将达到 4 个或以上（基线为 anthropics/skills、google/skills、cloudflare/security-audit-skill 三个）。 | community | 0.70 | 30 天 | 2026-12-08 | 截至到期日，在 GitHub 上用 org 账号（star 总数 >1000 的组织）检索仓库名含 "skills" 且 README 明确描述为 agent/LLM 能力包的项目；统计数量 ≥4 判为命中，≤3 判为落空。个人账号仓库不计入。 | `it_85641ad38767c9cc` `it_5d1070aaeb2b84b3` `it_77f9ddd43bbeeb71` `it_81446f2462dee9e2` |
| Anthropic 将在 30 天内在 Claude Code 的更新日志或官方文档中，加入"不再把通过 'Don't Ask Again' 授权的凭据以明文写入项目级配置文件"的变更说明。 | product | 0.60 | 30 天 | 2026-12-08 | 截至到期日，检查 Claude Code 的 CHANGELOG / release notes / 官方文档：若出现明确描述凭据脱敏、redaction 或不再持久化明文 secrets 的条目，判为命中；若 30 天内无任何相关条目且文档未变更，判为落空。 | `it_5186d80b7eef5626` `it_ee4da02d4a5e8d37` `it_df21541ba45a72aa` |
| 到 90 天后，GitHub 在公开预览中推出的新版 Pull Request 概览页将转为正式可用（GA），即 GitHub Changelog 中不再标注 public preview 或 beta 标签。 | product | 0.60 | 90 天 | 2027-02-06 | 截至到期日，检索 GitHub Changelog 与官方 docs：若出现该 PR overview 页面的 GA 公告，或该功能文档页移除 "public preview/beta" 标记，判为命中；若仍标注 public preview/beta 或功能被回滚下线，判为落空。 | `it_3bcdfa6e04aad911` `it_5186d80b7eef5626` `it_ee4da02d4a5e8d37` |
| 到 30 天后，GitHub 上以"扫描 AI 编码智能体配置文件中的凭据泄露"为主要用途、star 数超过 500 的仓库将达到 3 个或以上。 | policy | 0.55 | 30 天 | 2026-12-08 | 截至到期日，在 GitHub 检索同时满足以下条件的仓库：(a) README 明确定位为检测 agent 配置文件（如 CLAUDE.md、.claude/、settings、mcp 配置、skills 目录）中的密钥/凭据；(b) star ≥500；(c) 仓库创建或最近一次功能提交在到期日前 30 天内。数量 ≥3 判为命中，≤2 判为落空。 | `it_77f9ddd43bbeeb71` `it_5186d80b7eef5626` `it_c98d9678d269d780` |

### 证据条目对照（人工核验用）

- `it_85641ad38767c9cc` → anthropics/skills
- `it_5d1070aaeb2b84b3` → google/skills
- `it_77f9ddd43bbeeb71` → cloudflare/security-audit-skill
- `it_81446f2462dee9e2` → mattpocock/skills
- `it_5186d80b7eef5626` → Claude Code's "Don't Ask Again" exposes passwords in 1,122 public GitHub files
- `it_ee4da02d4a5e8d37` → microsoft/vscode
- `it_df21541ba45a72aa` → zed-industries/zed
- `it_3bcdfa6e04aad911` → GitHub New pull request overview page in public preview
- `it_5186d80b7eef5626` → Claude Code's "Don't Ask Again" exposes passwords in 1,122 public GitHub files
- `it_ee4da02d4a5e8d37` → microsoft/vscode
- `it_77f9ddd43bbeeb71` → cloudflare/security-audit-skill
- `it_5186d80b7eef5626` → Claude Code's "Don't Ask Again" exposes passwords in 1,122 public GitHub files
- `it_c98d9678d269d780` → sherlock-project/sherlock

> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。

---

_生成时间：2026-11-08T04:17:21.613365+00:00_
