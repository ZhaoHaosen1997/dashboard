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

## v0.3 - WSL 性能监控 📊

**目标**：前台展示 WSL 资源使用情况

- [ ] 安装 `psutil`
- [ ] 后端新增 API：`GET /api/wsl/metrics`
- [ ] 返回：CPU 使用率、内存使用率、磁盘使用率
- [ ] 前台页面展示性能数据（简洁卡片）
- [ ] 实时刷新（30s 间隔）

**返回示例**：
```json
{
  "cpu_percent": 23.5,
  "memory": {"total": 16000, "used": 8500, "percent": 53.1},
  "disk": {"total": 500, "used": 230, "percent": 46.0}
}
```

---

## v0.4 - Dashboard MCP Server 🤖

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

## v0.5 - AI 告警通知 🔔

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

## v0.6 - 访问统计 📈

**目标**：了解哪些服务最常用

- [ ] 数据库增加 `access_log` 表
- [ ] 点击卡片时记录访问日志
- [ ] 后端新增 API：`GET /api/stats/visits`
- [ ] 前端展示：访问热力图 / 排行榜
- [ ] 按日/周/月筛选

---

## v0.7 - 正式版 🎉

**目标**：功能完整，稳定运行

- [ ] 所有 v0.x 功能完善
- [ ] 移动端适配
- [ ] 深色模式
- [ ] 数据备份 / 恢复
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

---

_最后更新：2026-05-17_
