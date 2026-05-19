# 坚果云 WebDAV 对接指南

## 前置准备

1. 登录坚果云网页版 → **安全选项** → **第三方应用管理** → 添加应用，获取应用密码
2. 安装 Python 库：

```bash
pip install webdavclient3
```

> **注意：** pip 包名是 `webdavclient3`，但 import 时模块名是 `webdav3`：
>
> ```python
> from webdav3.client import Client as WebDavClient
> ```

## 客户端初始化

```python
from webdav3.client import Client as WebDavClient

client = WebDavClient({
    'webdav_hostname': 'https://dav.jianguoyun.com/dav/',
    'webdav_root': '/',
    'webdav_login': 'your@email.com',
    'webdav_password': '第三方应用密码',
    'disable_check': True,       # 必须设置，坚果云不支持 HEAD 请求
})
```

## 常用操作

**以下演示内容以项目名“dashboard”为例**

### 列出文件

```python
files = client.list('/dashboard/')
# 返回: ['20260519_205712.db', '20260519_215809.db']
# 注意：返回的是文件名，不含目录前缀
```

### 上传文件

```python
# 坚果云根目录只能放子文件夹，文件必须放在子目录内
client.mkdir('/dashboard/')  # 目录已存在时会跳过，不会报错
client.upload_sync('/dashboard/backup.db', '/local/backup.db')
```

### 下载文件

```python
# list() 返回的文件名需要手动拼接完整路径
client.download_sync('/dashboard/backup.db', '/local/backup.db')
```

### 删除文件

```python
client.clean('/dashboard/backup.db')
```

### 遍历云端目录（完整示例）

```python
files = client.list('/dashboard/')
for f in files:
    name = f.split('/')[-1]  # 取文件名
    if name and not f.endswith('/'):
        full_path = '/dashboard/' + name  # 拼完整路径
        print(f'找到文件: {name}')
        # 下载: client.download_sync(full_path, '/local/' + name)
```

## 坚果云 WebDAV 方法支持

| 方法 | 支持 | 备注 |
|------|------|------|
| PROPFIND | 是 | 列目录 |
| OPTIONS | 是 | 探测能力 |
| PUT | 是* | 仅限子目录内，根目录直接 PUT 返回 404 |
| GET | 是 | 下载文件 |
| MKCOL | 是 | 创建目录 |
| DELETE | 是 | 删除文件/空目录 |
| HEAD | 否 | 始终返回 403，所以需要 `disable_check: True` |
| LOCK/UNLOCK | 是 | 一般用不到 |

## webdav3 常用方法速查

| 方法 | 说明 |
|------|------|
| `client.list(remote_path)` | 列出目录内容，返回相对文件名列表 |
| `client.upload_sync(remote_path, local_path)` | 上传文件（同步） |
| `client.download_sync(remote_path, local_path)` | 下载文件（同步） |
| `client.mkdir(remote_path)` | 创建目录（注意：没有 `mkdir_sync`） |
| `client.clean(remote_path)` | 删除文件 |
| `client.check(remote_path)` | 检查资源是否存在（注意：坚果云不可用） |

## 目录结构建议

```
坚果云 WebDAV:
  /dav/
    dashboard/           ← 应用专用目录，存放备份文件
      20260519_205712.db
      20260519_215809.db
    我的文档/             ← 用户自己的文件
    ...                  ← 互不干扰
```

---

## 踩坑记录

### 坑 1：pip 包名 ≠ 模块名

```bash
pip install webdavclient3          # pip 包名
from webdav3.client import Client  # 模块名是 webdav3，不是 webdavclient3
```

`pip show webdavclient3` 可见实际安装到了 `webdav3/` 目录。

### 坑 2：上传返回 403 — HEAD 请求不支持

**现象：** `list()` 能列出文件，但 `upload()` 返回 403。

**原因：** `webdav3` 的 `upload_file()` 内部先调用 `check()` 方法，用 HEAD 请求验证父目录是否存在。坚果云对 HEAD 请求直接返回 403（不管认证是否正确），导致上传流程中断。

```http
HEAD /dav/ HTTP/1.1      → 403  （坚果云不允许）
PROPFIND /dav/ HTTP/1.1  → 207  （正常）
PUT /dav/file.txt HTTP/1.1 → 404  （根目录不允许）
```

**解决：** 创建 Client 时设置 `'disable_check': True`。

### 坑 3：根目录不允许 PUT 文件

**现象：** `PUT /dav/file.txt` 返回 404 `ObjectNotFound`。

**原因：** 坚果云 WebDAV 根目录只能存放子文件夹，文件必须放在子目录内。

### 坑 4：list() 返回相对路径

**现象：** `client.list('/dashboard/')` 返回 `['file.db']`，不是 `['/dashboard/file.db']`。

**原因：** `webdav3` 库内部把 list 的参数目录作为上下文，返回的是相对路径。下载时需要手动拼接。

### 坑 5：没有 mkdir_sync 方法

**现象：** `AttributeError: 'Client' object has no attribute 'mkdir_sync'`。

**原因：** 该库只有 `upload_sync`/`download_sync` 有 `_sync` 后缀，`mkdir` 本身就是同步的。

```python
client.mkdir('/dashboard/')      # 正确
client.mkdir_sync('/dashboard/')  # 报错！
```

---

_整理时间：2026-05-19_
