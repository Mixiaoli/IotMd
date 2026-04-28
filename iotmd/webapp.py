from __future__ import annotations

import os
from typing import Dict, Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, select

from iotmd.auth import create_token, hash_password, parse_token, verify_password
from iotmd.database import ModelConfig, QuestionRecord, User, db_session, init_db


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    can_use_ai: bool = True


class UserPermissionRequest(BaseModel):
    is_admin: bool
    can_use_ai: bool


class ModelConfigRequest(BaseModel):
    name: str
    provider: str = "openai-compatible"
    base_url: str = ""
    api_key: str = ""
    is_active: bool = False


app = FastAPI(title="IotMd Web API")

cors_origins = [x.strip() for x in os.getenv("IOTMD_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _token_from_header(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization.split(" ", 1)[1]


def get_current_user(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> User:
    token = _token_from_header(authorization)
    payload = parse_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期")
    user_id = payload.get("uid")
    with db_session() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        db.expunge(user)
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _openai_chat(base_url: str, api_key: str, model_name: str, question: str) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是 IotMd 的运维 AI 助手，请用简洁中文回答。"},
                {"role": "user", "content": question},
            ],
            "temperature": 0.3,
        },
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("模型返回为空")
    return str(choices[0].get("message", {}).get("content", "")).strip() or "模型未返回内容"


def _generate_ai_answer(question: str, model: Optional[ModelConfig]) -> str:
    if not model:
        return "未配置可用模型，请在后台 API 大模型管理里激活一个模型。"

    provider = (model.provider or "").lower()
    model_key = model.api_key or os.getenv("IOTMD_DEFAULT_MODEL_API_KEY", "")

    if provider == "mock" or not model.base_url or not model_key:
        tip = "当前为 mock 回答（请在后台配置 base_url + api_key）。"
        return "[{}] {}\n\n你的问题：{}".format(model.name, tip, question)

    try:
        return _openai_chat(model.base_url, model_key, model.name, question)
    except Exception as exc:  # noqa: BLE001
        return "模型调用失败：{}\n\n已回退 mock 回答：{}".format(exc, question)


@app.on_event("startup")
def startup() -> None:
    init_db()
    admin_name = os.getenv("IOTMD_ADMIN_USER", "admin")
    admin_password = os.getenv("IOTMD_ADMIN_PASSWORD", "admin123")
    with db_session() as db:
        exists = db.scalar(select(User).where(User.username == admin_name))
        if not exists:
            db.add(
                User(
                    username=admin_name,
                    password_hash=hash_password(admin_password),
                    is_admin=True,
                    can_use_ai=True,
                )
            )
        has_model = db.scalar(select(ModelConfig).where(ModelConfig.is_active.is_(True)))
        if not has_model:
            db.add(ModelConfig(name="default-model", provider="mock", is_active=True))


@app.get("/")
def root() -> Dict[str, str]:
    return {"service": "iotmd-web-api", "status": "ok"}


@app.post("/api/auth/login")
def login(data: LoginRequest) -> dict:
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == data.username))
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_token({"uid": user.id, "username": user.username, "is_admin": user.is_admin})
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
                "can_use_ai": user.can_use_ai,
            },
        }


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_use_ai": user.can_use_ai,
    }


@app.post("/api/chat")
def chat(data: ChatRequest, user: User = Depends(get_current_user)) -> dict:
    if not user.can_use_ai:
        raise HTTPException(status_code=403, detail="当前账号无 AI 使用权限")
    with db_session() as db:
        model = db.scalar(select(ModelConfig).where(ModelConfig.is_active.is_(True)))
        answer = _generate_ai_answer(data.question, model)
        rec = QuestionRecord(
            user_id=user.id,
            question=data.question,
            answer=answer,
            model_name=(model.name if model else "default-model"),
        )
        db.add(rec)
        db.flush()
        return {"id": rec.id, "answer": rec.answer, "model": rec.model_name}


@app.get("/api/history")
def history(user: User = Depends(get_current_user)) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(
            select(QuestionRecord)
            .where(QuestionRecord.user_id == user.id)
            .order_by(desc(QuestionRecord.created_at))
            .limit(100)
        ).all()
        return [
            {
                "id": r.id,
                "question": r.question,
                "answer": r.answer,
                "model": r.model_name,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


@app.get("/api/admin/users")
def admin_users(_: User = Depends(get_admin_user)) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(select(User).order_by(User.id.asc())).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "is_admin": u.is_admin,
                "can_use_ai": u.can_use_ai,
                "created_at": u.created_at.isoformat(),
            }
            for u in rows
        ]


@app.post("/api/admin/users")
def admin_create_user(data: UserCreateRequest, _: User = Depends(get_admin_user)) -> dict:
    with db_session() as db:
        exists = db.scalar(select(User).where(User.username == data.username))
        if exists:
            raise HTTPException(status_code=400, detail="用户名已存在")
        user = User(
            username=data.username,
            password_hash=hash_password(data.password),
            is_admin=data.is_admin,
            can_use_ai=data.can_use_ai,
        )
        db.add(user)
        db.flush()
        return {"id": user.id, "username": user.username}


@app.patch("/api/admin/users/{user_id}")
def admin_update_permission(user_id: int, data: UserPermissionRequest, _: User = Depends(get_admin_user)) -> dict:
    with db_session() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.is_admin = data.is_admin
        user.can_use_ai = data.can_use_ai
        db.add(user)
        return {"ok": True}


@app.get("/api/admin/questions")
def admin_questions(_: User = Depends(get_admin_user)) -> list[dict]:
    with db_session() as db:
        rows = db.execute(
            select(QuestionRecord, User.username)
            .join(User, User.id == QuestionRecord.user_id)
            .order_by(desc(QuestionRecord.created_at))
            .limit(200)
        ).all()
        return [
            {
                "id": rec.id,
                "username": username,
                "question": rec.question,
                "answer": rec.answer,
                "model": rec.model_name,
                "created_at": rec.created_at.isoformat(),
            }
            for rec, username in rows
        ]


@app.get("/api/admin/models")
def admin_models(_: User = Depends(get_admin_user)) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(select(ModelConfig).order_by(ModelConfig.id.asc())).all()
        return [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "base_url": m.base_url,
                "api_key": m.api_key,
                "is_active": m.is_active,
            }
            for m in rows
        ]


@app.post("/api/admin/models")
def admin_create_model(data: ModelConfigRequest, _: User = Depends(get_admin_user)) -> dict:
    with db_session() as db:
        if data.is_active:
            db.query(ModelConfig).update({"is_active": False})
        model = ModelConfig(**data.dict())
        db.add(model)
        db.flush()
        return {"id": model.id}


@app.patch("/api/admin/models/{model_id}/activate")
def admin_activate_model(model_id: int, _: User = Depends(get_admin_user)) -> dict:
    with db_session() as db:
        model = db.get(ModelConfig, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")
        db.query(ModelConfig).update({"is_active": False})
        model.is_active = True
        db.add(model)
        return {"ok": True, "active": model.name}
