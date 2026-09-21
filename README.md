# 🚀 start-page — 个人导航页

线上地址: **https://jiarjiar.github.io/start-page/**

一个纯静态的个人导航页（三栏布局 + 天气仪表盘 + 模拟时钟 + 动态天空背景），托管在 GitHub Pages，无服务器成本。

| 文件 | 作用 |
|---|---|
| `index.html` | 页面本体（纯静态单文件，无外部依赖） |
| `data.json` | 站点列表 —— **手工维护的固定列表** |
| `.github/workflows/deploy.yml` | push 后自动部署到 GitHub Pages |

## 怎么改站点列表

直接编辑 `data.json`，每个条目：

```json
{ "url": "https://example.com/", "title": "显示名", "host": "example.com", "folder": "工具", "pinned": false }
```

- `folder` 决定它出现在哪一栏：
  - `AI` → 🤖 第一栏
  - `常用` `工具` `文献` `UMD` `work` `KE` 等 → 🧪 工作 · 研究
  - `视频` `围棋` `社交` `其他` 等 → 🎮 生活 · 娱乐
- `pinned: true` 显示 📌 角标
- 改完 `git add data.json && git commit -m "..." && git push`，GitHub Actions 约 1 分钟自动部署

## 页面交互

- 搜索：按 `/` 聚焦，`Esc` 清空
- ✏️ 编辑模式：可临时隐藏/改名（只存在本机浏览器 localStorage，换设备不生效；要永久改请改 `data.json`）
- AI 栏顶部：时钟（平滑秒针）+ 天气（College Park 24 小时逐时 / 7 天预报，Boston、NYC、香港；美国城市用 NWS 官方源，香港用 Open-Meteo）+ 日出日落
- 背景天空随真实日落时间自动切换：白天 → 晚霞 → 夜景（星空）

## 隐私说明

- 站点列表完全手工维护，**不包含访问次数**，也**不来自任何浏览器历史**
- 页面无跟踪、无统计、无第三方脚本（图标从 Iconify / 站点 favicon 即时加载，断网时回落首字母块）
