#!/usr/bin/env bash
# start-page 一键更新: 重扫 Firefox → 更新 data.json → 推送到 GitHub (Pages 自动部署)
set -e
cd "$(dirname "$0")"

python3 fetch_bookmarks.py

git add data.json
if git diff --cached --quiet; then
  echo "📭 书签没有变化, 无需推送"
else
  git commit -m "📊 书签更新 $(date '+%Y-%m-%d %H:%M')"
  git push
  echo "🚀 已推送, GitHub Pages 约 1 分钟内自动更新"
fi
echo "✅ 完成 — 线上地址: https://jiarjiar.github.io/start-page/"
