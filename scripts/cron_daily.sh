#!/usr/bin/env bash
# WSL 本地 cron 备份（设计方案 §14.3）。
#
# GitHub Actions 是主通道，但本地 cron 保证数据不会因为 cache 失效而断档
# （Actions 无法持久化 SQLite，我们只能"尽力而为"地缓存它；本地库是权威副本）。
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
