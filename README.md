# Dashboard — 个人系统管理首页

一个自托管的服务器管理控制台，集中监控和管理本地/远程 Linux 服务。麻雀虽小五脏俱全——从服务启停、日志查看，到网络流量、GPU 锁管理，再到自动备份和资源告警，一站式搞定。

## 功能一览

### 首页仪表盘 (`/`)

- **服务卡片** — 拖拽排序，点击跳转，在线/离线状态一目了然
- **系统指标** — CPU / 内存 / 磁盘 / GPU 实时使用率 + 迷你趋势图（sparkline）
- **指标详情弹窗** — 点击任意指标卡片展开大图，切换 1h / 6h / 24h 时间范围
- **进程列表** — Top 5 CPU/内存进程
- **告警事件** — 资源告警时间线，异常时卡片红框脉冲提示
- **GPU 状态** — 实时利用率子指标（Util / Memory / Temp），锁状态可视

### 系统管理 (`/manage`)

- **系统 CRUD** — 添加 / 编辑 / 删除服务，配置图标、颜色、URL、服务名等
- **服务控制** — 一键 start / stop / restart（通过 systemd）
- **日志查看** — 实时拉取 journalctl 日志，支持 **按级别过滤**（ALL / ERROR / WARNING / INFO / DEBUG），一键开启 Tail 模式持续刷新
- **数据库备份** — 手动/自动备份，支持本地存储 + 坚果云 WebDAV 云端同步
- **WebDAV 配置** — 连接坚果云，云端文件列表浏览，一键上传/下载备份
- **网络监控** — 接口流量、Top 进程、活跃连接、新增 IP 告警
- **GPU 锁管理** — 手动锁定/解锁 GPU，自动空闲锁定策略

### 后台任务（启动时自动运行）

- **指标采集** — 每 5 分钟采样 CPU/内存/磁盘/GPU 使用率，保留 30 天
- **网络采集** — vnstat（流量）/ nethogs（进程）/ ss（连接）三路并行采集
- **资源告警** — 连续超阈值 N 次触发告警，支持**企业微信群机器人**和**浏览器桌面通知**两种渠道
- **自动备份** — 按配置的间隔对系统数据库定时备份，可自动轮转清理

## 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3.10+ / Flask / SQLite |
| **前端** | 纯 HTML/CSS/JS / Tailwind CSS / Lucide Icons / Chart.js |
| **系统工具** | systemd / journalctl / vnstat / nethogs / ss / psutil |
| **云同步** | 坚果云 WebDAV（webdavclient3） |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/ZhaoHaosen1997/dashboard.git
cd dashboard
```

### 2. 创建配置文件

```bash
cp backend/config.example.yml backend/config.yml
```

编辑 `backend/config.yml`，至少修改：
- `backup.base_dir` — 备份存放目录
- `network.monitor_ifaces` — 根据机器网卡修改（WSL 用 `eth1`，树莓派用 `eth0`）
- `alerts.thresholds` — 按需调整告警阈值
- `notify.wecom_webhook` — 如需企业微信告警，填入 Webhook URL

### 3. 安装依赖

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r ../requirements.txt
```

### 4. 启动

```bash
python app.py
```

打开浏览器访问 `http://localhost:8850` 即可。

### 5. 生产部署（systemd）

推荐使用 systemd 管理服务，参考模板：

```ini
[Unit]
Description=Dashboard
After=network.target

[Service]
Type=simple
User=<你的用户名>
WorkingDirectory=/home/<用户名>/applications/dashboard
ExecStart=/home/<用户名>/applications/dashboard/.venv/bin/python /home/<用户名>/applications/dashboard/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 项目结构

```
dashboard/
├── backend/
│   ├── app.py              # Flask 应用入口
│   ├── config.py           # 配置加载器（读取 config.yml）
│   ├── config.yml          # 本地配置（不提交 git，从 example 拷贝）
│   ├── config.example.yml  # 配置模板（含所有选项说明）
│   ├── db.py               # 数据库初始化 + 迁移
│   ├── utils.py            # 工具函数（systemctl、备份、加密）
│   ├── alerter.py          # 资源告警采集器
│   ├── net_collector.py    # 网络流量采集器
│   └── routes/
│       ├── systems.py      # 系统 CRUD + 服务控制 + 日志
│       ├── wsl.py          # 系统指标 + 进程信息
│       ├── backup.py       # 本地备份管理
│       ├── webdav.py       # 坚果云 WebDAV 集成
│       ├── net.py          # 网络监控 API
│       └── gpu.py          # GPU 锁管理
├── templates/
│   ├── index.html          # 首页仪表盘
│   └── manage.html         # 系统管理页
├── static/
│   └── js/                 # 前端静态资源（Tailwind、Lucide）
├── requirements.txt
└── README.md
```

## API 概览

### 系统管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/systems` | 获取所有系统 |
| POST | `/api/systems` | 添加系统 |
| PUT | `/api/systems/<id>` | 更新系统 |
| DELETE | `/api/systems/<id>` | 删除系统 |
| PATCH | `/api/systems/reorder` | 拖拽排序 |
| GET | `/api/systems/<id>/status` | 在线检测 |

### 服务控制 & 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/systems/<id>/service/<action>` | 服务启停（start/stop/restart） |
| GET | `/api/systems/<id>/logs?lines=N` | 获取 journalctl 日志 |

### 系统指标

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/wsl/metrics` | 当前 CPU/内存/磁盘/GPU 使用率 |
| GET | `/api/wsl/metrics/history?hours=N` | 历史指标数据（图表用） |
| GET | `/api/wsl/events` | 最近进程事件 |
| GET | `/api/wsl/alerts/status` | 当前活跃告警 |
| GET | `/api/wsl/alerts/history` | 告警历史记录 |

### 网络监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/net/summary?hours=N` | 流量汇总 + Top 进程 + 新 IP |
| GET | `/api/net/traffic` | 接口流量时序数据 |
| GET | `/api/net/processes` | 进程网络流量 |
| GET | `/api/net/connections` | 活跃连接列表 |
| GET | `/api/net/alerts` | 网络异常告警 |
| POST | `/api/net/alerts/<id>/ack` | 确认告警 |
| GET/POST/DELETE | `/api/net/whitelist` | IP 白名单管理 |

### GPU 锁

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/gpu/lock` | 查询当前锁状态 |
| PUT | `/api/gpu/lock` | 手动锁定 GPU |
| DELETE | `/api/gpu/lock` | 手动解锁 GPU |
| GET | `/api/gpu/lock/auto` | 自动锁策略配置 |
| PUT | `/api/gpu/lock/auto` | 更新自动锁策略 |
| GET | `/api/gpu/lock/check` | 实时检查 GPU 锁 |
| GET | `/api/gpu/lock/log` | 锁操作历史 |

### 备份 & WebDAV

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/webdav/config` | 坚果云连接配置 |
| POST | `/api/webdav/check` | 测试 WebDAV 连接 |
| GET | `/api/webdav/list` | 云端文件列表 |
| POST | `/api/webdav/upload` | 上传备份到云端 |
| POST | `/api/webdav/download` | 从云端下载备份 |
| GET | `/api/backup/list/<sid>` | 系统备份记录 |
| GET | `/api/backup/list/dashboard` | Dashboard 自身备份记录 |
| POST | `/api/backup/perform/<sid>` | 手动备份系统数据库 |
| POST | `/api/restore/perform/<sid>` | 恢复备份 |

## 数据库说明

SQLite 数据库 `config.db` 首次运行自动创建，核心表：

| 表名 | 用途 |
|------|------|
| `systems` | 系统/服务配置 |
| `metrics` | CPU/内存/磁盘/GPU 历史指标 |
| `backup_records` | 备份历史记录 |
| `webdav_config` | 坚果云 WebDAV 连接配置（密码 Fernet 加密） |
| `gpu_lock_log` | GPU 锁操作日志 |
| `net_traffic` | 网络流量数据（保留 90 天） |
| `net_process` | 网络进程快照（保留 30 天） |
| `net_conn` | 网络连接快照（保留 7 天） |
| `net_alert` | 网络异常告警（保留 90 天） |

## 配置参考

`backend/config.yml` 完整选项见 `backend/config.example.yml`，关键配置项：

- `server.host/port` — 监听地址和端口（默认 `0.0.0.0:8850`）
- `network.monitor_ifaces` — 网卡列表（WSL: `eth1`，树莓派: `eth0`，VPN: `tailscale0`）
- `alerts.thresholds` — CPU/内存/磁盘/GPU 告警阈值（%）
- `alerts.silence_minutes` — 同指标告警静默期
- `notify.wecom_webhook` — 企业微信群机器人 Webhook URL
- `notify.browser_notification` — 浏览器桌面通知开关
- `metrics.interval` — 指标采样间隔（秒）
- `backup.base_dir` — 备份文件存放目录

## 依赖的环境工具

部分功能依赖 Linux 系统工具（仅限 Linux/WSL 部署）：

- `systemctl` — 服务启停
- `journalctl` — 日志查看
- `vnstat` — 网络流量统计（需安装 `vnstat` 并启动 `vnstatd` 服务）
- `nethogs` — 进程级网络流量（需 `sudo setcap` 授予非 root 权限）
- `ss` — 连接快照（Linux 预装）
- `nvidia-smi` — GPU 监控（可选，无 GPU 自动降级）

## License

MIT
