# VixFutures

VIX 期货期限结构曲线，参考 volchart.io 的信息结构实现。

- 实时数据：CBOE VX 期货延迟结算价（月度合约，过滤周合约）
- 历史曲线：volchart.io 历史端点
- 现货 VIX：Yahoo Finance `^VIX`，失败降级 CNBC / CBOE 日收盘
- 独立交叉验证：SquawkFlow
- **零第三方 Python 依赖**，只用标准库

## 目录

| 文件 | 用途 |
|---|---|
| `server.py` | 本地实时服务 + 数据抓取/清洗；`--once --json` 自检 |
| `static/` | 实时页前端（原生 HTML/CSS/SVG） |
| `build_static.py` | 生成单文件静态快照；`--direct` 可直连上游，不依赖本地服务 |
| `scripts/update_node.py` | 龙竹节点一键更新：git pull → 取数 → 写网站目录 → 补首页链接 |
| `run_update.bat` | Windows 计划任务入口，日志写 `D:\tmp\vixfutures_update.log` |
| `dist/vixfutures.html` | 已发布的公网快照成品 |

## 本地运行

```
D:\.venv\Scripts\python.exe server.py --port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

自检：

```
D:\.venv\Scripts\python.exe server.py --once --json
```

生成本地快照：

```
D:\.venv\Scripts\python.exe build_static.py --source http://127.0.0.1:8765 --out dist/vixfutures.html
```

## 龙竹节点部署（定时更新并发布）

### 1. 克隆仓库

```
git clone https://github.com/idea2realClaw/VixFutures.git D:\Github\VixFutures
```

### 2. 手动跑一次，确认能写网站目录

```
D:\Github\VixFutures\run_update.bat
```

预期：

- `D:\DragonServer\www\vixfutures.html` 被生成/覆盖
- 首页 `index.html` 导航若无 `/vixfutures.html` 链接则自动补上（幂等）
- 日志：`D:\tmp\vixfutures_update.log`，末尾 `EXIT=0`

### 3. 注册 Windows 计划任务（每天 10:00，北京时间）

```
schtasks /Create /TN "VixFuturesAutoUpdate" /TR "D:\Github\VixFutures\run_update.bat" /SC DAILY /ST 10:00 /F
```

说明：CBOE 结算时间约为美中时间 19:36（北京时间次日 09:36），10:00 之后跑可拿到当日结算。

查看/删除任务：

```
schtasks /Query /TN "VixFuturesAutoUpdate"
schtasks /Delete /TN "VixFuturesAutoUpdate" /F
```

### 4. 验证

```
type D:\tmp\vixfutures_update.log
```

浏览器访问 `https://weworkwos.tailf2b74d.ts.net/vixfutures.html`，页面顶部「页面模式」显示最新生成时间。

## 注意事项

- 节点需能访问 `www-api.cboe.com`、`cdn.cboe.com`、`volchart.io`、`query1.finance.yahoo.com`、`api.squawkflow.com`。
- 更新脚本**直接写** `D:\DragonServer\www`，不需要 FTP 账号，凭据不落盘。
- 访问计数用 `hits.sh` 的 SVG 徽章，统计的是图片请求数（含刷新/爬虫），不是独立访客。
- 若 `broadcast\sync_site.py` 从主站同步覆盖了 `index.html`，下次更新脚本会自动把 VIX 链接补回去。
- 页面数据是快照，不会在浏览器端变化；每次任务运行重新生成并覆盖。

## 数据说明

仅供研究参考，不构成投资建议。免费上游均为延迟或日终数据，时间戳以页面顶部显示为准。
