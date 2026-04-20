from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

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


app = FastAPI(title="IotMd Web")


def _generate_ai_answer(question: str, model: ModelConfig | None) -> str:
    model_name = model.name if model else "default-model"
    return f"[{model_name}] 已收到问题：{question}\n\n这是示例 AI 回答，请接入真实大模型 API。"


def _token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization.split(" ", 1)[1]


def get_current_user(authorization: str | None = Header(default=None, alias="Authorization")) -> User:
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
def index() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent / "frontend" / "index.html")


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
