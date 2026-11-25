"""Account verification and recovery for a configured private SMTP relay."""

from contextlib import closing
from email.message import EmailMessage
import hashlib
import os
import secrets
import smtplib
import sqlite3
import ssl
import time
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class MailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    purpose: Literal["verify", "reset"]


class Redeem(BaseModel):
    token: str = Field(min_length=20, max_length=160)
    password: str | None = Field(default=None, min_length=12, max_length=128)


def init_mail(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS verified_accounts(account TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS mail_tokens(
          token TEXT PRIMARY KEY,account TEXT,purpose TEXT,expires INTEGER);
        CREATE TABLE IF NOT EXISTS mail_limits(address TEXT PRIMARY KEY,since INTEGER,count INTEGER);
    """)


def send_link(email, purpose, token):
    from .server import origin

    message = EmailMessage()
    message["Subject"] = (
        "Verifica tu correo" if purpose == "verify" else "Restablece tu contraseña"
    )
    message["From"] = os.environ["STUDIO_MAIL_FROM"]
    message["To"] = email
    # A URL fragment stays in the browser and is removed before rendering the form.
    message.set_content(
        "Abre este enlace de Writer Studio en los próximos 20 minutos.\n"
        + origin
        + "/studio#"
        + urlencode({"action": purpose, "token": token})
    )
    with smtplib.SMTP(
        os.environ["STUDIO_SMTP_HOST"],
        int(os.getenv("STUDIO_SMTP_PORT", "587")),
        timeout=8,
    ) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv("STUDIO_SMTP_USER"):
            smtp.login(
                os.environ["STUDIO_SMTP_USER"], os.environ["STUDIO_SMTP_PASSWORD"]
            )
        smtp.send_message(message)


@router.post("/api/mail/request", status_code=202)
def request_link(payload: MailRequest, request: Request):
    from .server import root

    if not os.getenv("STUDIO_SMTP_HOST") or not os.getenv("STUDIO_MAIL_FROM"):
        raise HTTPException(503, "El correo de staging está sin configurar")
    email = payload.email.strip().casefold()
    if any(c in email for c in "\r\n") or email.count("@") != 1:
        raise HTTPException(422, "Revisa el correo")
    now = int(time.time())
    addr = request.client.host if request.client else "local"
    with closing(sqlite3.connect(root / "accounts.db")) as db:
        init_mail(db)
        with db:
            db.execute("DELETE FROM mail_limits WHERE since<?", (now - 900,))
            db.execute(
                "INSERT INTO mail_limits VALUES(?,?,1) ON CONFLICT(address) DO UPDATE SET count=count+1",
                (addr, now),
            )
            count = db.execute(
                "SELECT count FROM mail_limits WHERE address=?", (addr,)
            ).fetchone()[0]
        if count > 8:
            raise HTTPException(429, "Espera antes de solicitar otro enlace")
        row = db.execute("SELECT id FROM accounts WHERE email=?", (email,)).fetchone()
        if row:
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            with db:
                db.execute("DELETE FROM mail_tokens WHERE expires<?", (now,))
                db.execute(
                    "INSERT INTO mail_tokens VALUES(?,?,?,?)",
                    (digest, row[0], payload.purpose, now + 1200),
                )
            try:
                send_link(email, payload.purpose, token)
            except (OSError, smtplib.SMTPException, ValueError, KeyError):
                with db:
                    db.execute("DELETE FROM mail_tokens WHERE token=?", (digest,))
                # Return the same response for known and unknown email addresses.
    return {
        "message": "Si la cuenta existe y el correo está disponible, recibirás un enlace."
    }


@router.post("/api/mail/redeem")
def redeem(payload: Redeem):
    from .server import root, derive

    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    with closing(sqlite3.connect(root / "accounts.db")) as db, db:
        init_mail(db)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT account,purpose FROM mail_tokens WHERE token=? AND expires>?",
            (digest, int(time.time())),
        ).fetchone()
        if not row:
            raise HTTPException(400, "Enlace inválido o vencido")
        if row[1] == "reset":
            if not payload.password:
                raise HTTPException(422, "Introduce la nueva contraseña")
            salt = secrets.token_bytes(16)
            db.execute(
                "UPDATE accounts SET salt=?,password=? WHERE id=?",
                (salt, derive(payload.password, salt), row[0]),
            )
            db.execute("DELETE FROM sessions WHERE account=?", (row[0],))
        db.execute("INSERT OR IGNORE INTO verified_accounts VALUES(?)", (row[0],))
        db.execute("DELETE FROM mail_tokens WHERE account=?", (row[0],))
    return {"message": "Cuenta actualizada. Inicia sesión."}
