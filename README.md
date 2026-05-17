# Dashboard - 个人系统管理首页

一个简洁的个人系统管理平台，用于集中管理和监控本地 Web 服务。

## 功能特性

- **系统卡片展示** - 彩色图标、名称、描述、端口
- **状态实时检测** - 在线/离线状态自动检测，每30秒刷新
- **CRUD 管理** - 添加、编辑、删除系统
- **拖拽排序** - 自由调整卡片顺序
- **统计面板** - 顶部显示在线/离线数量

## 技术栈

- **后端**: Flask + SQLite
- **前端**: 纯 HTML/CSS/JS + TailwindCSS + Lucide 图标
- **状态检测**: HTTP HEAD 请求

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

**Windows:**
```batch
start.bat
```

**Linux/WSL:**
```bash
./start.sh
```

### 3. 访问

打开浏览器访问: http://localhost:8850

## 项目结构

```
C:\mycode\dashboard\
├── app.py              # Flask 后端 (API + 数据库)
├── requirements.txt    # Python 依赖
├── config.db          # SQLite 数据库 (自动生成)
├── favicon.ico        # 网站图标
├── templates/
│   └── index.html     # 前端页面
├── start.sh           # Linux/WSL 启动脚本
├── stop.sh            # Linux/WSL 停止脚本
├── deploy.sh          # Linux/WSL 部署脚本
└── start.bat          # Windows 启动脚本
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/systems` | 获取所有系统 |
| POST | `/api/systems` | 添加系统 |
| PUT | `/api/systems/<id>` | 更新系统 |
| DELETE | `/api/systems/<id>` | 删除系统 |
| PATCH | `/api/systems/reorder` | 批量更新排序 |
| GET | `/api/systems/<id>/status` | 检测系统状态 |

## 数据库字段

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| name | TEXT | 系统名称 |
| url | TEXT | 访问地址 |
| port | INTEGER | 端口号 |
| description | TEXT | 描述 |
| icon | TEXT | Lucide 图标名 |
| color | TEXT | 主题色 |
| sort_order | INTEGER | 排序顺序 |
| is_active | INTEGER | 是否启用 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

## 预装系统

1. **PrintFlow-3D** - 3D打印副业管理系统 (端口 18848)
2. **Usage Data Viewer** - 字节API使用量查看 (端口 8849)

## 可用图标

支持所有 [Lucide Icons](https://lucide.dev/icons/)，常用图标：

| 图标名 | 显示 |
|--------|------|
| box | 📦 |
| printer | 🖨️ |
| bar-chart-2 | 📊 |
| database | 🗄️ |
| server | 🖥️ |
| cloud | ☁️ |
| code | 💻 |
| settings | ⚙️ |
| shopping-cart | 🛒 |
| folder | 📁 |

## 注意事项

- 服务默认监听 `0.0.0.0:8850`，局域网可访问
- 状态检测使用 HTTP HEAD 请求，响应码 < 500 视为在线
- 数据库文件 `config.db` 首次运行自动创建
- 生产环境建议使用 gunicorn 替代 Flask 内置服务器
