# IotMd（纯 Web 应用）

IotMd 已调整为 **纯 Web 应用架构**：
- 已砍掉命令行业务流程（不再提供 CLI 采集/问答模式）。
- 使用 **FastAPI + Vue3 + MySQL**。
- 用户必须登录后，才可使用 AI 交互。
- 提供后台：用户权限管理、问题列表记录管理、API 大模型管理。

## 数据库 SQL 文件

已提供可直接导入的 MySQL 初始化脚本：

- `sql/iotmd_mysql.sql`

导入示例：

```bash
mysql -u root -p < sql/iotmd_mysql.sql
```

## 技术栈

- 后端：FastAPI + SQLAlchemy
- 前端：Vue3（单页）
- 数据库：MySQL（`pymysql`）

## 环境变量

- `IOTMD_DATABASE_URL`（默认：`mysql+pymysql://iotmd:iotmd123@127.0.0.1:3306/iotmd?charset=utf8mb4`）
- `IOTMD_ADMIN_USER`（默认 `admin`）
- `IOTMD_ADMIN_PASSWORD`（默认 `admin123`）
- `IOTMD_AUTH_SECRET`

## 启动方式（Web）

```bash
pip install -r requirements.txt
pip install -e .
uvicorn iotmd.webapp:app --host 0.0.0.0 --port 8765
```

访问：

- `http://127.0.0.1:8765/`

## 功能说明

### 登录与鉴权
- `POST /api/auth/login`
- `GET /api/auth/me`

### AI 交互与历史
- `POST /api/chat`
- `GET /api/history`

### 管理后台（管理员）
- 用户权限管理
  - `GET /api/admin/users`
  - `POST /api/admin/users`
  - `PATCH /api/admin/users/{user_id}`
- 问题列表记录管理
  - `GET /api/admin/questions`
- API 大模型管理
  - `GET /api/admin/models`
  - `POST /api/admin/models`
  - `PATCH /api/admin/models/{model_id}/activate`

> `POST /api/chat` 当前为示例回答函数，后续可替换为真实大模型 API 调用。
