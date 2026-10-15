# 贡献指南

感谢愿意一起把 aipulse 做得更准。这个项目的成败不取决于功能多少，而取决于**预言是否可信**——
所以下面几件事比"多写代码"重要。

## 环境

```bash
git clone https://github.com/tochikoma777/aipulse && cd aipulse
uv sync
uv run aipulse init
uv run aipulse doctor
uv run pytest
```

WSL2 用户注意：**代码必须放在 WSL 原生文件系统**（不要放 `/mnt/c/`）。跨文件系统 I/O 极慢、
SQLite 文件锁与 git 行为都会异常。

## 提交前

```bash
uv run ruff check . && uv run ruff format --check .   # lint + 格式
uv run mypy src/aipulse                               # strict（core/schema/analysis 尤其严格）
uv run pytest                                         # 必须全绿，且不需要网络与密钥
```

`uv run pre-commit install` 可以在 commit 时自动跑这三件事。

CI（`.github/workflows/ci.yml`）在**无密钥环境**运行同样的检查——任何依赖 key 或真实网络的用例
都必须用 `monkeypatch` / `respx` 隔离或 `pytest.skip` 显式跳过，不得静默假装通过。

## 几条硬规矩（会直接影响 PR 能否合并）

1. **预言必须可证伪**：不要放宽模糊措辞黑名单或 `falsifiable_criteria` 的校验。宁可当天只产出 2 条，
   也不要为了凑数放水——记分板的可信度是项目唯一的护城河。
2. **"无法验证"只由系统的证据门槛产生**，LLM 不允许输出 `unverifiable`（否则它会变成逃避 miss 的软出口）。
3. **统计口径不能动**：`pending` / `unverifiable` 不计入分母；`partial` 按 `outcome = 0.5` 计入；
   校准分桶必须保留低置信桶 `[0.05, 0.5)`。
4. **Web 页面只读**：`src/aipulse/web/` 通过 SQLite 只读连接取数（`mode=ro`），不得引入任何写操作。
   已有回归测试 `tests/unit/test_web.py::test_readonly_engine_rejects_writes` 守着这条线。
5. **不实现微信 / X（Twitter）采集**：相关内容只走 `data/inbox/*.md` 手动投喂。
6. **新数据源必须实测**：先用 `scripts/probe_sources.py` 验证端点真实可用，并把响应快照放进 `tests/fixtures/`；
   **不要凭想象写字段解析**。
7. **prompt 不写进 `.py`**：一律 `prompts/**.j2`，头部带 YAML front-matter（`model_tier` / `temperature` / `purpose`）。
8. **阈值不硬编码**：权重、阈值、源配置全部走 `configs/*.yaml`。
9. **`mode: off` 下不得发出任何模型请求**（单测用 `respx` 断言零调用）；未配置 key 时自动降级，不报错退出。
10. **SSOT 文档只读**：`docs/AI Pulse 设计方案 v1` 与 `docs/AI Pulse · Agent 开发执行手册 v1` 由项目负责人
    维护并覆盖，请**不要**直接修改；你的结论请写进 `docs/开发日志.md` / `docs/数据源手册.md` / `docs/新增数据源指南.md`。

## 提交信息

Conventional Commits，例如：

```
feat(m4): 每日流水线自动产出 scoreboard.md 与 signals.json
fix(web): 模板里 dict.items 被 Jinja 解析成方法本身
docs: 补 signals.json 的字段说明
```

## 开发文档入口

| 想做什么 | 先读 |
|---|---|
| 了解整体架构与决策 | [`docs/AI Pulse 设计方案 v1`](AI%20Pulse%20设计方案%20v1) |
| 按阶段任务卡执行 | [`docs/AI Pulse · Agent 开发执行手册 v1`](AI%20Pulse%20·%20Agent%20开发执行手册%20v1) |
| 新增 / 修复数据源 | [`docs/新增数据源指南.md`](新增数据源指南.md)、[`docs/数据源手册.md`](数据源手册.md) |
| 理解某段代码为什么这么写 | [`CODEBUDDY.md`](../CODEBUDDY.md)（模块职责 + 已归档的坑） |
| 看每阶段实测结论 | [`docs/开发日志.md`](开发日志.md) |
