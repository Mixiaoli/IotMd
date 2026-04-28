# IotMd（纯 Web 应用，前后端分离）

IotMd 已改为 **前后端分离的 Web 应用**：
- 后端：FastAPI API
- 前端：Vue3 静态页面（`frontend/`）
- 数据库：MySQL

## 快速开始

1) 初始化数据库

```bash
mysql -u root -p < sql/iotmd_mysql.sql
```

2) 启动后端

```bash
export IOTMD_DATABASE_URL='mysql+pymysql://iotmd:your_password@127.0.0.1:3306/iotmd?charset=utf8mb4'
export IOTMD_AUTH_SECRET='replace-with-strong-secret'
export IOTMD_CORS_ORIGINS='http://127.0.0.1:5173,http://localhost:5173'
uvicorn iotmd.webapp:app --host 0.0.0.0 --port 8765
```

3) 启动前端

```bash
python -m http.server 5173 -d frontend
```

浏览器访问 `http://127.0.0.1:5173`。

## AI 大模型 Key 配置位置

### 方案 1（推荐）
管理员登录后，在后台“API 大模型管理”中配置：
- name
- provider（`openai-compatible` / `mock`）
- base_url
- api_key
- 激活模型

### 方案 2（默认兜底）
设置环境变量：

```bash
export IOTMD_DEFAULT_MODEL_API_KEY='sk-xxxx'
```

当数据库模型配置里 `api_key` 为空时，会自动使用该环境变量。

## 详细部署文档

请看：`docs/WEB_DEPLOYMENT.md`
