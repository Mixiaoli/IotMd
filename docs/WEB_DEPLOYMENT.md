# IotMd 前后端分离部署说明

## 1. 架构

- 后端 API：FastAPI（`iotmd/webapp.py`）
- 前端页面：`frontend/`（静态文件，独立部署）
- 数据库：MySQL（初始化脚本：`sql/iotmd_mysql.sql`）

## 2. 后端配置

必须先配置环境变量：

```bash
export IOTMD_DATABASE_URL='mysql+pymysql://iotmd:your_password@127.0.0.1:3306/iotmd?charset=utf8mb4'
export IOTMD_ADMIN_USER='admin'
export IOTMD_ADMIN_PASSWORD='admin123'
export IOTMD_AUTH_SECRET='replace-with-strong-secret'
export IOTMD_CORS_ORIGINS='http://127.0.0.1:5173,http://localhost:5173'
```

可选默认模型 Key（当模型管理里 api_key 留空时使用）：

```bash
export IOTMD_DEFAULT_MODEL_API_KEY='sk-xxxx'
```

启动后端：

```bash
uvicorn iotmd.webapp:app --host 0.0.0.0 --port 8765
```

## 3. 前端配置

前端是独立静态页面，默认请求 `http://127.0.0.1:8765`。

本地启动前端（任选其一）：

```bash
python -m http.server 5173 -d frontend
# 或
npx serve frontend -l 5173
```

打开：

- `http://127.0.0.1:5173`

## 4. AI 大模型 Key 在哪里配？

你有两种配置方式：

### 方式 A（推荐）：后台页面配置模型

登录管理员后，在“API 大模型管理”里新增模型：

- `name`：模型名（例如 `gpt-4o-mini`）
- `provider`：`openai-compatible`（或 `mock`）
- `base_url`：例如 `https://api.openai.com/v1`
- `api_key`：直接填你的 key
- 激活该模型

### 方式 B：环境变量默认 Key

如果模型配置里的 `api_key` 为空，后端会读取环境变量：

- `IOTMD_DEFAULT_MODEL_API_KEY`

## 5. MySQL 初始化

```bash
mysql -u root -p < sql/iotmd_mysql.sql
```

## 6. 常见问题

- 前端报跨域：确认 `IOTMD_CORS_ORIGINS` 包含前端域名。
- 返回 mock 回答：检查模型是否激活、`base_url` 和 `api_key` 是否正确。
- 登录失败：确认管理员账号环境变量与数据库中账号一致。
