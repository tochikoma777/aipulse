#!/usr/bin/env bash
# M6c 知识库导出 cron（方案 E：不跑本地 daily，只 pull + export）。
#
# 前提：本地 daily 不安装/不运行，因此工作区不会因 data/reports 变脏。
# 安装（示例时间，按需调整；Actions 是 UTC 00:00）：
#   crontab -e
#   # UTC 00:30 = 北京 08:30，排在 Actions 之后
#   30 0 * * * /home/<you>/projects/aipulse/scripts/cron_knowledge.sh
#
# 手动验证：
#   scripts/cron_knowledge.sh; tail -n 40 data/logs/cron_knowledge.log

set -euo pipefail

# 项目根目录 = 本脚本所在目录的上一级（不依赖调用者的 cwd）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p data/logs
LOG="data/logs/cron_knowledge.log"

{
  echo "── $(date -Is) cron_knowledge 开始 ──"
} >>"$LOG"

# 优先用 venv 内的可执行文件，避免 cron 环境没有 uv/PATH
if [[ -x "$ROOT/.venv/bin/aipulse" ]]; then
  AIPULSE_BIN="$ROOT/.venv/bin/aipulse"
else
  AIPULSE_BIN="uv run aipulse"
fi

# 只检查已跟踪/已暂存改动；data/inbox、未跟踪日志等不应长期阻断导出。
# 本地提交不在此判断内，由下面的 pull --ff-only 负责失败退出。
#
# ★ S5：trend / debate 产物是**生成物**（每周重跑会改写），它们变脏不该阻断导出——
#   否则重跑一次周报，知识库导出就永久停摆。只忽略这两个目录，其余路径照常检查。
if ! git diff --quiet -- . ':!data/reports/trend' ':!data/reports/debate' ||
  ! git diff --cached --quiet -- . ':!data/reports/trend' ':!data/reports/debate'; then
  echo "$(date -Is) 工作区有已跟踪改动，跳过 pull/export" >>"$LOG"
  exit 0
fi

# 必须 HTTP/1.1（HTTP/2 会超时）；--ff-only 禁止 merge commit。
git -c http.version=HTTP/1.1 pull --ff-only || {
  echo "$(date -Is) pull failed" >>"$LOG"
  exit 1
}
echo "$(date -Is) pull OK" >>"$LOG"

# export 必须检查退出码：只 >>"$LOG" 2>&1 会让 set -e 静默退出且没有失败日志。
if $AIPULSE_BIN knowledge export >>"$LOG" 2>&1; then
  total=$(sed -n 's/^> 条目总数：\([0-9][0-9]*\).*/\1/p' \
    "$ROOT/data/knowledge/index.md" 2>/dev/null | head -n 1 || true)
  echo "$(date -Is) export OK total=${total:-unknown}" >>"$LOG"
else
  code=$?
  echo "$(date -Is) export FAILED exit=$code" >>"$LOG"
  exit "$code"
fi
