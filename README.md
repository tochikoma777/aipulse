# aipulse · AI 脉搏

> 每日自动采集 AI 领域热点，**不只整理，还给出可回测的推演与预言**。

> 🚧 **WIP / 开发中**：当前已完成 **M0（项目骨架与数据源探测）**，正在推进 M1（采集器与去重）。
> 功能尚不完整，但骨架可运行、数据源已逐个实测——探测结论见 [`docs/数据源手册.md`](docs/数据源手册.md)。

## 一句话定位

每天 10 分钟知道「今天 AI 圈发生了什么值得看的」，并且看到这个系统过去下的判断到底准不准。

## Roadmap

| 阶段 | 核心产出 | 状态 |
|---|---|---|
| **M0** | 项目骨架 + 数据源探测（fixtures + 数据源手册 + `doctor`） | ✅ 已完成 |
| M1 | 6 个采集器 + inbox + 三级去重 | ⬜ 待做 |
| M2 | 热度打分 / 聚类 + 每日简报（零花费可跑） | ⬜ 待做 |
| M3 | ★ 预言系统：可证伪预言 + 到期验证 + 命中率/校准度 | ⬜ 待做 |
| M4 | GitHub Actions 自动化 + Web 看板 + 开源发布包装 | ⬜ 待做 |
| M5 | 周期趋势长文 + 多角色辩论 | ⬜ 待做 |

## 快速开始

```bash
# 环境：WSL2 / Python 3.11 / uv
uv sync

uv run aipulse --help          # 查看全部子命令
uv run aipulse init            # 建库 + 生成目录骨架 + .env
uv run aipulse doctor          # 环境体检：Python/LLM key/代理/磁盘/数据库/各源连通性
```

数据源探测（M0 产物，需要联网）：

```bash
uv run python scripts/probe_sources.py             # 5 个 API 源 + 全部 RSS feed
uv run python scripts/probe_sources.py --no-cache   # 跳过 SQLite 响应缓存
```

## 三档运行模式（设计目标）

| 档位 | LLM 调用 | 说明 |
|---|---|---|
| `off` | 零次 | 采集 / 打分 / 聚类 / 手写预言 / 自动验证 / 校准统计全可用 |
| `hybrid` | 2-3 次/日 | off 全部 + 自动预言生成 + 主编点评 |
| `full`（默认） | 全部 | 追加多角色辩论与周期长文 |

**没有 API key 也能用**——未配置 key 时自动降级到 `off` 档，只提示一次，不报错退出。

## 数据源

GitHub Trending / arXiv / HuggingFace Daily Papers / Hacker News / Reddit r/LocalLLaMA / RSS（英文主干 + 中文补充），外加 `inbox` 手动投喂。

- 每个源的端点、真实字段、限速与失效降级路径见 [`docs/数据源手册.md`](docs/数据源手册.md)。
- **不抓取微信公众号与 X（Twitter）**，相关内容请走 `inbox add` 手动投喂。

## 目录结构

```
configs/      default.yaml / sources.yaml / scoring.yaml
src/aipulse/  cli core schema collectors normalize store llm analysis reasoning render notify pipeline utils
scripts/      probe_sources.py（数据源探测）
tests/        fixtures（真实响应快照）/ unit / integration
docs/         数据源手册 · 架构说明 · 开发日志
```

## 合规与数据来源

- 只存储标题 + 摘要 + 公开指标，**不做全文转载**，均标注来源与原链接。
- Reddit 仅使用公开 RSS，不存储用户身份信息。
- 数据来源与合规声明详见 `docs/数据源手册.md`。

## License

[MIT](LICENSE)
