# 🚀 start-page — 网页版收藏夹

从 Firefox 自动生成你的**最常访问网站**导航页，免费托管在 GitHub Pages，无需任何服务器。

线上地址: **https://jiarjiar.github.io/start-page/**

## 这是什么

| 文件 | 作用 |
|---|---|
| `fetch_bookmarks.py` | 核心脚本：读 Firefox 数据库 → 聚合去重 → 生成 `data.json` |
| `data.json` | 生成物（不含访问次数，隐私友好） |
| `index.html` | 页面本体（纯静态单文件，无任何外部依赖） |
| `pins.json` | 手动置顶规则（可选） |
| `update.sh` | 一键更新：重扫 Firefox → 自动 commit → push |
| `.github/workflows/deploy.yml` | push 后自动部署到 GitHub Pages |

## 日常使用

```bash
./update.sh        # 一键更新（写代码用的机器上运行）
```

浏览器打开 https://jiarjiar.github.io/start-page/ ；页面顶部搜索框支持 `/` 键聚焦，分类 chips 点击过滤，点击卡片新标签页打开。

## 工作原理

1. `fetch_bookmarks.py` 复制 Firefox 的 `places.sqlite`（只读副本，不影响 Firefox 运行）
2. 从历史记录中按域名聚合（消除 Gmail 多账号、日历日期、session 号等 URL 变体），取每个站点的"代表 URL"
3. 分类优先级：**强制规则表 > 收藏夹文件夹 > 域名规则表 > 其他**
4. 输出 TOP 50（`--limit` 可调），**访问次数只用于排序，不写入 data.json**

## 如何修改规则

所有规则都在 `fetch_bookmarks.py` 顶部的配置区：

- `SPECIAL_FOLDER` — 强制分类（优先级最高），如 Gmail/日历 → 常用
- `DOMAIN_CATEGORY` — 域名后缀 → 分类
- `REPRESENTATIVE` — 代表 URL 模板，如 chatgpt.com → 主页
- `NOISE_HOSTS` / `is_noise()` — 噪音过滤（搜索页、OAuth 跳转等）
- `FOLDER_RENAME` — 收藏夹文件夹 → 友好分类名

改完运行 `./update.sh` 即可生效。

## pins.json — 置顶

```json
{
  "pins": [
    "chatgpt.com",                  // 按 host 精确匹配（不含子域）
    "https://mail.google.com"       // 或完整 URL 前缀匹配
  ]
}
```

置顶项显示 📌 并排在最前（顺序 = pins.json 里写的顺序）。

## 隐私说明

- `data.json` 随仓库公开，**只含 URL/标题/分类，不含访问次数**
- `pins.json` 里的规则也公开，但只是 host 名，无敏感信息
- 整个页面无跟踪、无统计、无第三方脚本（favicon 图标从 Google 服务即时加载，断网时回落首字母色块）

## 更新频率

页面数据 = 你本机 Firefox 的历史。想更新时本地跑一次 `./update.sh`（约 3 秒，GitHub Actions 自动重新部署）。
