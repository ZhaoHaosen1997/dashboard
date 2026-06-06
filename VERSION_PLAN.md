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

## v0.5.1 - WSL 性能监控增强 ✅

**目标**：大幅扩展监控范围，覆盖 GPU（大模型推理）、磁盘 I/O、网络、进程等

### 新增监控指标
- [x] GPU 监控（NVIDIA）
  - [x] GPU 利用率（%）
  - [x] GPU 显存使用量/总量
  - [x] GPU 温度
  - [x] GPU 功耗（如有）
- [x] 磁盘 I/O
  - [x] 读写速率（MB/s）
  - [x] IOPS（可选）
- [x] 网络 I/O
  - [x] 上传/下载速率（MB/s）
  - [x] 总发送/接收字节数（见 v0.5.2）
- [x] 内存详情
  - [x] 已用 / 缓存 / 可用
  - [x] Swap 使用量
- [x] 进程 Top-N
  - [x] CPU 占用 Top 5
  - [x] 内存占用 Top 5
- [x] 负载（load average）

### 前端展示
- [x] 监控面板重新设计（网格布局）
- [x] GPU 卡片高亮（有大模型运行时）
- [x] 历史趋势图（24h 折线图）
- [x] 网卡/磁盘 I/O 实时速率

### 技术方案
| 指标 | 实现方式 |
|------|----------|
| GPU | `pynvml`（NVIDIA）或 `nvidia-ml-py`，WSL 内调用 `nvidia-smi` |
| 磁盘 I/O | `psutil.disk_io_counters()` |
| 网络 I/O | `psutil.net_io_counters()` |
| 进程 Top | `psutil.process_iter()` + sorted |
| 负载 | `os.getloadavg()`（Linux） |

### 注意事项
- GPU 监控在 WSL2 下需要 NVIDIA CUDA 驱动支持，需检测可用性
- 采集频率保持 5 分钟，实时展示仍然 30s 刷新
- 历史数据量增大，需评估数据库存储策略

---

## v0.5.2 - 网络流量深度监控 ✅

**目标**：系统级 + 进程级 + 连接级三层网络监控，发现未知入访

### 数据采集层 (WSL 后台线程)
- [x] **vnstat 集成** — 读取 `/proc/net/dev` 计数器，不受采样损失
  - 监控接口：eth1（主网卡）+ tailscale0（VPN）
  - 提供按小时/天的出入流量汇总
  - Dashboard 每小时解析 vnstat JSON → `net_traffic` 表
- [x] **nethogs 进程级流量** — 每 60 秒采集一次
  - 按 PID/进程名 统计 sent_bytes / recv_bytes
  - 存入 `net_process` 表，支持按小时聚合
- [x] **ss 连接追踪** — 每 60 秒快照
  - 记录所有 TCP/UDP 连接的 remote_ip:port → 进程映射
  - 存入 `net_conn` 表
- [x] **异常检测**
  - 新 IP 检测：过去 24h 未见过的远程 IP → `net_alert`
  - 每天每个 IP 只告警一次（去重）

### 数据库新增
| 表 | 用途 | 保留周期 |
|------|------|----------|
| `net_traffic` | 按小时/接口 流量汇总 | 90 天 |
| `net_process` | 按进程/分钟 流量采样 | 30 天 |
| `net_conn` | 连接快照 (remote IP + 端口 + 进程) | 7 天 |
| `net_alert` | 异常告警 | 90 天 |

### API 端点
| 端点 | 功能 |
|------|------|
| `GET /api/net/summary?hours=24` | 概览：总流量、Top10 进程、最新告警、活跃连接数 |
| `GET /api/net/traffic?days=7&interface=eth1&granularity=hour` | 流量趋势数据（hour/day） |
| `GET /api/net/processes?hours=24&limit=20` | 进程流量排行 + Top5 进程逐小时时序 |
| `GET /api/net/connections?hours=24&limit=100&group_by=ip` | 连接分析（按 IP 或按进程聚合） |
| `GET /api/net/alerts?days=7&unacknowledged=1` | 异常告警列表 |
| `POST /api/net/alerts/<id>/ack` | 确认告警 |

### 技术方案
| 组件 | 实现 |
|------|------|
| vnstat | 系统服务 `vnstatd`，每小时 `vnstat --json h` |
| nethogs | 子进程 tracemode `nethogs -t -d 60 eth1`，需 `cap_net_admin,cap_net_raw` |
| ss | 每分钟 `ss -tunap` 子进程 |
| 采集线程 | `net_collector.py` — 3 个守护线程 + 1 个清理线程 |
| 前端 | 待 v0.5 前端重构时一并展示 |

### 已知限制
- nethogs 进程名显示完整路径（如 `/home/zhaohaosen/.hermes/hermes-agent/venv/bin/python`），待优化为 basename
- 首次运行 24h 内所有 IP 都是"新 IP"，告警量较大（正常现象，随时间推移减少）
- WSL2 环境下 nethogs 只能看到 WSL 内部的网络流量

---

## v0.5.3 - IP 告警白名单 ✅

**目标**：减少告警噪音，局域网/Tailscale 等可信 IP 段自动忽略

- [x] 数据库新增 `net_whitelist` 表（cidr / 备注）
- [x] 管理后台添加白名单配置页面
- [x] 采集器 `_detect_new_ips` 加入白名单检查
- [x] 预置默认白名单：`192.163.20.0/24`（局域网）、`100.64.0.0/10`（Tailscale）、`127.0.0.0/8`（本地）
- [x] API: `GET/POST/DELETE /api/net/whitelist`

---

## v0.5.4 - GPU 锁管理 ✅

**目标**：通过 HTTP API 管理 GPU 使用锁，附带自动加锁/解锁的定时检查

### GPU 锁 API（调用 `gpu_lock.sh`）
- [x] `GET /api/gpu/lock` — 查看锁状态（locked / who）
- [x] `PUT /api/gpu/lock` — 加锁 `{"who":"comfyui"}`
- [x] `DELETE /api/gpu/lock` — 解锁
- [x] `GET /api/gpu/lock/check` — 快速检测（200空闲 / 409占用）
- [x] Windows 开发环境兜底：脚本不存在时返回 `{"locked":false, "note":"..."}`

### 自动加锁/解锁
- [x] 后台线程每 15s 检查 GPU 利用率（nvidia-smi）
- [x] 配置化：空闲阈值 5%、空闲锁定时长 60s、繁忙解锁时长 30s
- [x] 空闲超时 → 自动加锁（who=`auto-idle`）
- [x] 自动锁期间 GPU 恢复繁忙 → 自动解锁
- [x] `GET/PUT /api/gpu/lock/auto` — 查看/修改自动配置

### 前端
- [x] GPU 卡片底部新增锁状态指示条（🔒已锁定 / 🔓空闲）
- [x] 点击按钮一键加锁/解锁（who=`dashboard`）

### 技术方案
| 组件 | 实现 |
|------|------|
| 脚本调用 | `subprocess.run` 调用 `~/scripts/gpu_lock.sh` |
| 自动检查 | 独立 daemon 线程 `gpu-auto-lock` |
| GPU 探测 | `nvidia-smi --query-gpu=utilization.gpu` |

---

## v0.6 - 访问统计 📈

**目标**：了解哪些服务最常用

- [ ] 数据库增加 `access_log` 表
- [ ] 点击卡片时记录访问日志
- [ ] 后端新增 API：`GET /api/stats/visits`
- [ ] 前端展示：访问热力图 / 排行榜
- [ ] 按日/周/月筛选

---

## v0.7 - Dashboard MCP Server 🤖

**目标**：标准化暴露 Dashboard 能力，跨平台复用（Hermes / Claude / IDE 通用）

> 当前 Hermes 已可通过 REST API 调用，MCP 提供标准化 schema 和自动工具发现，换 AI 平台时无需重新对接。

- [ ] 将 Dashboard 封装为 MCP Server
- [ ] 暴露工具：
  - [ ] `list_services` - 列出所有服务
  - [ ] `check_service_status` - 检测指定服务状态
  - [ ] `restart_service` - 重启服务
  - [ ] `get_wsl_metrics` - 获取 WSL 性能数据（含 GPU）
  - [ ] `get_service_logs` - 获取服务日志
  - [ ] `get_net_alerts` - 获取网络异常告警
  - [ ] `get_net_traffic` - 获取流量统计
- [ ] 在 Hermes 中配置 Dashboard MCP
- [ ] 测试：QQ 发消息 → Hermes → Dashboard MCP → 返回结果

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

_最后更新：2026-05-22_
