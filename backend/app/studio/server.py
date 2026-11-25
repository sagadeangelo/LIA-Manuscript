"""Private, invitation-only staging entry point. The desktop API remains independent."""

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import limits
from .mail import init_mail, router as mail_router
from ..api.routes import literary_step4, manuscripts, projects, step6_editor
from ..core.database import initialize, workspace_dir

root = Path(os.environ["STUDIO_DATA_DIR"]).resolve()
root.mkdir(parents=True, exist_ok=True, mode=0o700)
invite = os.environ["STUDIO_INVITE"]
if len(invite) < 24:
    raise RuntimeError("STUDIO_INVITE requiere al menos 24 caracteres")
origin = os.environ["STUDIO_ORIGIN"].rstrip("/")
parts = urlsplit(origin)
if (
    parts.username
    or parts.password
    or parts.query
    or parts.fragment
    or parts.path
    or not parts.hostname
):
    raise RuntimeError("STUDIO_ORIGIN debe ser un origen sin ruta")
local = parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}
if not local and not origin.startswith("https://"):
    raise RuntimeError("Configura HTTPS para staging remoto")
static = Path(__file__).with_name("static")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
with closing(sqlite3.connect(root / "accounts.db")) as db:
    limits.initialize(db)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, email TEXT UNIQUE, salt BLOB, password BLOB);
    CREATE TABLE IF NOT EXISTS plans(account TEXT PRIMARY KEY, plan TEXT NOT NULL, expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS plan_events(account TEXT,event TEXT,plan TEXT,PRIMARY KEY(account,event));
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, account TEXT, expires INTEGER);
    CREATE TABLE IF NOT EXISTS attempts(address TEXT PRIMARY KEY, since INTEGER, count INTEGER);
    """)


app.include_router(mail_router)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    invitation: str = Field(default="", max_length=256)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def derive(password, salt):
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024**2
    )


@app.middleware("http")
async def scope(request: Request, call_next):
    path = request.url.path
    if (
        path != "/webhooks/stripe-test"
        and request.method not in {"HEAD", "GET"}
        and request.headers.get("origin") != origin
    ):
        return JSONResponse({"detail": "Origen no permitido"}, 403)
    marker = None
    if path.startswith("/api/") and path not in {
        "/api/login",
        "/api/register",
        "/api/mail/request",
        "/api/mail/redeem",
    }:
        with closing(sqlite3.connect(root / "accounts.db")) as db:
            row = db.execute(
                "SELECT account FROM sessions WHERE token=? AND expires>?",
                (token_hash(request.cookies.get("lia_session", "")), time.time()),
            ).fetchone()
        if not row:
            return JSONResponse({"detail": "Inicia sesión"}, 401)
        request.state.account = row[0]
        if "/manuscripts/" in path:
            with closing(sqlite3.connect(root / "accounts.db")) as db:
                plan = db.execute(
                    "SELECT plan,expires FROM plans WHERE account=?", (row[0],)
                ).fetchone()
            required = None
            if path.endswith(("/review", "/dictionary", "/corrected")):
                required = "staylo"
            elif (
                "/export/" in path
                or "/layouts" in path
                or path.endswith("/export-docx")
            ):
                required = "publish"
            elif path.endswith(("/translation-jobs", "/translate-chapter")):
                required = "manuscript"
            if required and (
                not plan
                or plan[1] <= time.time()
                or plan[0] not in {"trial", "studio", required}
            ):
                return JSONResponse(
                    {"detail": "La herramienta requiere un plan vigente"}, 403
                )
            if required and (
                request.method != "GET"
                or "/export/" in path
                or path.endswith("/interior.pdf")
            ):
                try:
                    limits.consume(root / "accounts.db", row[0], required)
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, exc.status_code)
        marker = workspace_dir.set(root / str(UUID(row[0])))
        # Job status lives in process memory. Authorize the manuscript before accessing it.
        if "/translation-progress/" in path:
            from ..core.database import connect

            parts = path.strip("/").split("/")
            with connect() as tenant:
                owned = (
                    len(parts) >= 7
                    and tenant.execute(
                        "SELECT 1 FROM manuscripts WHERE project_id=? AND id=?",
                        (parts[2], parts[4]),
                    ).fetchone()
                )
            if not owned:
                workspace_dir.reset(marker)
                return JSONResponse({"detail": "Manuscrito desconocido"}, 404)
    try:
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
            }
        )
        return response
    finally:
        if marker is not None:
            workspace_dir.reset(marker)


@app.post("/api/register", status_code=201)
@app.post("/api/login")
def authenticate(payload: Credentials, request: Request, response: Response):
    email = payload.email.strip().casefold()
    if email.count("@") != 1 or any(c.isspace() for c in email):
        raise HTTPException(422, "Revisa el correo")
    address = request.client.host if request.client else "local"
    now = int(time.time())
    with closing(sqlite3.connect(root / "accounts.db", timeout=10)) as db:
        with db:
            db.execute("DELETE FROM attempts WHERE since < ?", (now - 600,))
            db.execute(
                "INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(address) DO UPDATE SET count=count+1",
                (address, now),
            )
            count = db.execute(
                "SELECT count FROM attempts WHERE address=?", (address,)
            ).fetchone()[0]
        if count > 30:
            raise HTTPException(429, "Espera antes de volver a intentarlo")
        if request.url.path == "/api/register":
            if not secrets.compare_digest(payload.invitation.encode(), invite.encode()):
                raise HTTPException(403, "Invitación incorrecta")
            account, salt = str(uuid4()), secrets.token_bytes(16)
            with db:
                try:
                    db.execute(
                        "INSERT INTO accounts VALUES(?,?,?,?)",
                        (account, email, salt, derive(payload.password, salt)),
                    )
                except sqlite3.IntegrityError:
                    raise HTTPException(409, "Registro no disponible")
                db.execute(
                    "INSERT INTO plans VALUES(?,?,?)",
                    (account, "trial", now + 7 * 86400),
                )
                marker = workspace_dir.set(root / account)
                try:
                    initialize()
                finally:
                    workspace_dir.reset(marker)
        else:
            row = db.execute(
                "SELECT id,salt,password FROM accounts WHERE email=?", (email,)
            ).fetchone()
            candidate = derive(payload.password, row[1] if row else bytes(16))
            if not row or not secrets.compare_digest(candidate, row[2]):
                raise HTTPException(401, "Credenciales incorrectas")
            account = row[0]
        if os.getenv("STUDIO_SMTP_HOST"):
            init_mail(db)
            if not db.execute(
                "SELECT 1 FROM verified_accounts WHERE account=?", (account,)
            ).fetchone():
                return {"verification_required": True}
        token = secrets.token_urlsafe(32)
        with db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (token_hash(token), account, now + 28800),
            )
        response.set_cookie(
            "lia_session",
            token,
            httponly=True,
            secure=not local,
            samesite="strict",
            max_age=28800,
        )
    return {"email": email}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    with closing(sqlite3.connect(root / "accounts.db")) as db, db:
        db.execute(
            "DELETE FROM sessions WHERE token=?",
            (token_hash(request.cookies.get("lia_session", "")),),
        )
    response.delete_cookie("lia_session")
    return {"ok": True}


for router in (
    projects.router,
    manuscripts.router,
    literary_step4.router,
    step6_editor.router,
):
    app.include_router(router)


@app.get("/studio/staylo")
@app.get("/studio/manuscript")
@app.get("/studio/publish")
@app.get("/studio/proyectos")
@app.get("/studio/suscripcion")
@app.get("/studio/cuenta")
@app.get("/studio")
def studio():
    return FileResponse(static / "index.html")


app.mount("/studio/assets", StaticFiles(directory=static), name="studio-assets")

from .editorial import router as editorial_router

app.include_router(editorial_router)


from typing import Literal


class SandboxOrder(BaseModel):
    event: UUID
    plan: Literal["studio", "staylo", "manuscript", "publish"]


@app.get("/api/subscription")
def subscription(request: Request):
    with closing(sqlite3.connect(root / "accounts.db")) as db:
        plan, expires = db.execute(
            "SELECT plan,expires FROM plans WHERE account=?", (request.state.account,)
        ).fetchone()
    return {
        "plan": plan,
        "expires": expires,
        "sandbox": True,
        "checkout_enabled": os.getenv("STUDIO_STRIPE_TEST_KEY", "").startswith(
            "sk_test_"
        )
        and bool(os.getenv("STUDIO_STRIPE_TEST_WEBHOOK")),
    }


@app.post("/api/subscription/simulate")
def simulate_order(order: SandboxOrder, request: Request):
    account = request.state.account
    with closing(sqlite3.connect(root / "accounts.db", timeout=10)) as db, db:
        inserted = db.execute(
            "INSERT OR IGNORE INTO plan_events VALUES(?,?,?)",
            (account, str(order.event), order.plan),
        ).rowcount
        if inserted:
            db.execute(
                "UPDATE plans SET plan=?,expires=? WHERE account=?",
                (order.plan, int(time.time()) + 30 * 86400, account),
            )
        elif (
            db.execute(
                "SELECT plan FROM plan_events WHERE account=? AND event=?",
                (account, str(order.event)),
            ).fetchone()[0]
            != order.plan
        ):
            raise HTTPException(409, "La operación ya corresponde a otro plan")
    return {"sandbox": True, "activated": bool(inserted)}


def require_admin(request: Request):
    secret = os.getenv("STUDIO_ADMIN_TOKEN", "")
    header = request.headers.get("authorization", "")
    if len(secret) < 32 or not secrets.compare_digest(
        header.encode(), ("Bearer " + secret).encode()
    ):
        raise HTTPException(403, "Acceso administrativo requerido")
    return True


@app.get("/api/admin/summary")
def admin_summary(request: Request):
    require_admin(request)
    with closing(sqlite3.connect(root / "accounts.db")) as db:
        return {
            "daily_limits": dict(db.execute("SELECT tool,allowance FROM daily_limits")),
            "usage": dict(
                db.execute("SELECT tool,sum(calls) FROM daily_usage GROUP BY tool")
            ),
            "accounts": db.execute("SELECT count(*) FROM accounts").fetchone()[0],
            "active_plans": dict(
                db.execute(
                    "SELECT plan,count(*) FROM plans WHERE expires>? GROUP BY plan",
                    (time.time(),),
                )
            ),
            "simulated_events": db.execute(
                "SELECT count(*) FROM plan_events"
            ).fetchone()[0],
            "live_revenue": 0,
        }


@app.get("/studio/admin")
def admin_page():
    return FileResponse(static / "admin.html")


from .checkout import router as checkout_router

app.include_router(checkout_router)


class DailyLimit(BaseModel):
    tool: Literal["staylo", "manuscript", "publish"]
    allowance: int = Field(ge=0, le=100000)


@app.put("/api/admin/limits")
def change_limit(payload: DailyLimit, request: Request):
    require_admin(request)
    with closing(sqlite3.connect(root / "accounts.db")) as db, db:
        db.execute(
            "UPDATE daily_limits SET allowance=? WHERE tool=?",
            (payload.allowance, payload.tool),
        )
    return payload


from .print_edition import router as print_router

app.include_router(print_router)
