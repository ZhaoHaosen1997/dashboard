# Dashboard 版本更新计划

> 日方长，慢慢做。—— 浩森

---

## v0.1 - 基础框架 ✅

- [x] Flask 后端 + SQLite
- [x] 系统卡片展示
- [x] 新增/编辑/删除（模态框）
- [x] 拖拽排序
- [x] 状态自动检测（30s）
- [x] WSL systemd 部署
- [x] favicon 图标

---

## v0.2 - 前台/后台分离 ✅

**目标**：前台简洁好看（导航 + 未来 WSL 监控），后台集中管理

### 前台（默认页面）
- [x] 重新设计前台，尽可能简洁好看
- [x] 上方「添加系统」按钮 → 改为「管理」按钮
- [x] 卡片只展示：图标、名称、状态、描述
- [x] 点击卡片直接跳转系统 URL
- [x] 拖拽排序
- [x] 预留 WSL 性能监控展示区域（v0.3 实现）

### 管理后台（点击「管理」进入）
- [x] 新建页面 `/manage`（或 Modal 全屏）
- [x] 集成功能：
  - [x] 添加/编辑/删除系统
  - [x] 服务启动/停止/重启
  - [x] 查看服务日志
- [x] 管理后台需要简单确认（避免误触）

**技术方案**：
- 前台：`/`（简洁展示）
- 后台：`/manage`（集中管理，或 Modal 全屏覆盖）

---

## v0.3 - WSL 性能监控 ✅

**目标**：前台展示 WSL 资源使用情况

- [x] 安装 `psutil`
- [x] 后端新增 API：`GET /api/wsl/metrics`（实时数据）
- [x] 返回：CPU 使用率、内存使用率、磁盘使用率、uptime
- [x] 前台页面展示性能数据（简洁卡片）
- [x] 实时刷新（30s 间隔）
- [x] 后台采样线程：每 5 分钟存储一次指标到数据库
- [x] 历史数据 API：`GET /api/wsl/metrics/history?hours=24`
- [x] 前端 sparkline 迷你趋势图（24h）
- [x] 开关机事件记录（boot/shutdown 自动检测）
- [x] 事件查询 API：`GET /api/wsl/events`
- [x] 数据自动清理（保留 7 天）

**返回示例**：
```json
{
  "cpu_percent": 23.5,
  "memory": {"total": 16000, "used": 8500, "percent": 53.1},
  "disk": {"total": 500, "used": 230, "percent": 46.0}
}
```

---

## v0.4 - 数据备份 ✅

**目标**：按系统独立配置，备份所有接入系统的 SQLite 数据库文件

### 备份配置（每个系统独立设置，默认关闭）
- [x] 数据库路径配置（每个系统可单独填写 db 文件路径）
- [x] 备份开关（默认：关闭，需手动开启）
- [x] 自动备份间隔（可配置：每日 / 每 7 日 / 每 30 日，默认不自动）
- [x] 保留备份份数（可配置，默认 3）
- [x] 配置入口：管理后台 → 每个系统的编辑弹窗内

#### 本地备份
- [x] 手动触发备份（管理后台按钮，按系统触发）
- [x] 自动触发备份（仅对已开启备份的系统生效）：
  - **每日首次启动**：开机服务就绪后异步触发（默认关闭，需开启备份开关）
  - **间隔上限**：超过设定间隔未备份则强制触发
  - **启动防抖**：1 小时内已备份则跳过
- [x] 备份文件命名：`YYYYMMDD_HHMMSS.db`
- [x] 按保留份数自动清理旧备份

#### 坚果云 WebDAV 备份
- [x] WebDAV 配置（URL、用户名、密码/token）
- [x] 手动触发上传 / 下载
- [x] 展示云端和本地最新备份时间和数据库文件大小，让你决定同步方向
- [x] 不自动同步，仅手动操作

#### 恢复功能
- [x] 查看备份列表（按系统选择）
- [x] 恢复流程：停止服务 → 备份当前为「恢复前版本」→ 覆盖数据库 → 重启服务
- [x] 「恢复前版本」命名加 `pre_restore_` 前缀

### 技术方案

| 功能 | 实现方式 |
|------|----------|
| 数据库拷贝 | `shutil.copy2` |
| WebDAV | `webdav3.client` 或 `requests` + WebDAV API |
| 异步任务 | Python `threading.Thread` 后台执行 |
| 启动检测 | Flask 启动完成后检查「上次备份时间」 |
| 敏感信息加密 | `cryptography.fernet`（密钥存 `~/.dashboard/.key`，权限 600） |

### 密钥文件管理
```
~/.dashboard/
└── .key          # Fernet 密钥文件，仅 owner 可读（chmod 600）
```

**首次运行时自动生成密钥**，无需手动配置。

### 备份目录结构
```
/home/zhaohaosen/backup/
├── dashboard/
│   ├── 20250518_143022.db
│   ├── 20250517_083015.db
│   └── pre_restore_20250518_160530.db
├── printflow-3d/
│   └── ...
└── usage-data-viewer/
    └── ...
```

---

## v0.5 - Dashboard MCP Server 🤖

**目标**：让 Hermes 能调用 Dashboard 的能力

- [ ] 将 Dashboard 封装为 MCP Server
- [ ] 暴露工具：
  - `list_services` - 列出所有服务
  - `check_service_status` - 检测指定服务状态
  - `restart_service` - 重启服务
  - `get_wsl_metrics` - 获取 WSL 性能数据
  - `get_service_logs` - 获取服务日志
- [ ] 在 Hermes 中配置 Dashboard MCP
- [ ] 测试：QQ 发消息 → Hermes → Dashboard MCP → 返回结果

---

## v0.6 - AI 告警通知 🔔

**目标**：服务异常自动通过 QQ 推送

- [ ] 后端增加异常检测逻辑（连续 3 次离线）
- [ ] 配置 Webhook 推送到 Hermes
- [ ] Hermes 分析故障原因
- [ ] QQ 推送告警消息
- [ ] 告警历史记录（数据库）

**推送示例**：
```
⚠️ 服务异常告警
服务：PrintFlow-3D
状态：离线（已持续 5 分钟）
可能原因：端口冲突 / 进程崩溃 / 服务器重启
建议：检查 WSL 中 `systemctl status printflow-3d`
```

---

## v0.7 - 访问统计 📈

**目标**：了解哪些服务最常用

- [ ] 数据库增加 `access_log` 表
- [ ] 点击卡片时记录访问日志
- [ ] 后端新增 API：`GET /api/stats/visits`
- [ ] 前端展示：访问热力图 / 排行榜
- [ ] 按日/周/月筛选

---

## v0.8 - 正式版 🎉

**目标**：功能完整，稳定运行

- [ ] 所有 v0.x 功能完善
- [ ] 移动端适配
- [ ] 深色模式
- [ ] 文档完善（部署文档、API 文档）
- [ ] 生产环境测试（gunicorn + nginx）

---

## 技术方案待定

| 功能 | 技术方案 |
|------|----------|
| 服务控制 | `subprocess` → `systemctl` |
| 性能监控 | `psutil` 库 |
| 日志查看 | `journalctl` / `subprocess` |
| MCP Server | FastMCP 或自研 |
| AI 告警 | Webhook → Hermes |
| 数据备份 | `shutil.copy2` / `webdav3.client` |

---

_最后更新：2026-05-19_
