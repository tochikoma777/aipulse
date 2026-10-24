#!/usr/bin/env bash
# WSL 本地 cron 备份（设计方案 §14.3）。
#
# ★ 权威副本是 `data/reports/`（已 commit 的日报 JSON），**不是** `data/aipulse.db`。
#   原因：SQLite 只是当日运行的中间库，git 不跟踪（`.gitignore` 的 `data/*.db`）；
#   Actions 只能靠 cache「尽力而为」地续命，本地这份也随时会停更。
#   实测 2026-10-23：本地库停在 10-17，日报已到 10-23 —— 拿库当基准会直接读错。
#   跨期分析（trend / debate / selfcheck / knowledge export）一律读 reports，不读库。
#
# GitHub Actions 是主通道；本地 cron 只是补位，避免 Actions 偶发失败时当天完全断档。
#
# 安装（WSL 内）：
#   crontab -e
#   # 每天北京时间 07:35（避开 Actions 的 07:00，减少并发写同一份 codes 的概率）
#   35 7 * * * /home/<you>/projects/aipulse/scripts/cron_daily.sh
#
# 手动验证：
#   scripts/cron_daily.sh; tail -n 40 data/logs/cron.log

set -euo pipefail

# 项目根目录 = 本脚本所在目录的上一级（不依赖调用者的 cwd）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p data/logs
LOG="data/logs/cron.log"

{
  echo "── $(date -Is) cron_daily 开始 ──"
} >>"$LOG"

# 优先用 venv 内的可执行文件，避免 cron 环境没有 uv/PATH
if [[ -x "$ROOT/.venv/bin/aipulse" ]]; then
  AIPULSE_BIN="$ROOT/.venv/bin/aipulse"
else
  AIPULSE_BIN="uv run aipulse"
fi

# 本地不是 Actions 环境：actions_only 的源会被跳过且不计失败（红线 12）
unset AIPULSE_ENV

if $AIPULSE_BIN daily --date today >>"$LOG" 2>&1; then
  echo "$(date -Is) OK" >>"$LOG"
else
  code=$?
  echo "$(date -Is) FAILED exit=$code" >>"$LOG"
  exit "$code"
fi
