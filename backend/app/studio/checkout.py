"""One-time test passes; signed callbacks never accept live Stripe events."""

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class Checkout(BaseModel):
    plan: Literal["studio", "staylo", "manuscript", "publish"]
    order_id: UUID


def prepare(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS checkout_orders(
          id TEXT PRIMARY KEY, account TEXT, plan TEXT, cents INTEGER, session TEXT UNIQUE, paid INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS stripe_events(id TEXT PRIMARY KEY);
    """)


@router.post("/api/checkout")
def start(payload: Checkout, request: Request):
    from .server import origin, root

    key = os.getenv("STUDIO_STRIPE_TEST_KEY", "")
    if not key.startswith("sk_test_") or not os.getenv("STUDIO_STRIPE_TEST_WEBHOOK"):
        raise HTTPException(503, "El procesador de pruebas está sin configurar")
    account, order_id = request.state.account, str(payload.order_id)
    # Nominal staging amount, never a published commercial price.
    amount = 1000
    with closing(sqlite3.connect(root / "accounts.db")) as db, db:
        prepare(db)
        db.execute(
            "INSERT OR IGNORE INTO checkout_orders(id,account,plan,cents) VALUES(?,?,?,?)",
            (order_id, account, payload.plan, amount),
        )
        row = db.execute(
            "SELECT account,plan,paid FROM checkout_orders WHERE id=?", (order_id,)
        ).fetchone()
        if row != (account, payload.plan, 0):
            raise HTTPException(409, "La orden ya está registrada")
    try:
        result = httpx.post(
            "https://api.stripe.com/v1/checkout/sessions",
            auth=(key, ""),
            headers={"Idempotency-Key": order_id},
            timeout=15,
            data={
                "mode": "payment",
                "success_url": origin + "/studio",
                "cancel_url": origin + "/studio",
                "client_reference_id": order_id,
                "line_items[0][quantity]": "1",
                "line_items[0][price_data][currency]": "mxn",
                "line_items[0][price_data][unit_amount]": str(amount),
                "line_items[0][price_data][product_data][name]": "Prueba Studio · "
                + payload.plan,
            },
        )
        result.raise_for_status()
        session = result.json()
        if session.get("livemode") is not False or not session["id"].startswith(
            "cs_test_"
        ):
            raise ValueError()
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Stripe no confirmó el checkout de prueba")
    with closing(sqlite3.connect(root / "accounts.db")) as db, db:
        db.execute(
            "UPDATE checkout_orders SET session=? WHERE id=?", (session["id"], order_id)
        )
    return {"url": session["url"], "sandbox": True}


@router.post("/webhooks/stripe-test")
async def stripe_event(request: Request):
    from .server import root

    secret = os.getenv("STUDIO_STRIPE_TEST_WEBHOOK", "")
    if not secret.startswith("whsec_"):
        raise HTTPException(503, "Webhook de prueba sin configurar")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise HTTPException(413)
        body.extend(chunk)
    fields = [
        part.partition("=")
        for part in request.headers.get("Stripe-Signature", "").split(",")
    ]
    try:
        stamp = next(v for k, _, v in fields if k == "t")
        if abs(time.time() - int(stamp)) > 300:
            raise ValueError()
        expected = hmac.new(
            secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, v) for k, _, v in fields if k == "v1"):
            raise ValueError()
        event = json.loads(body)
        if event["livemode"] is not False:
            raise ValueError()
        event_id = event["id"]
        obj = event["data"]["object"]
    except (ValueError, KeyError, TypeError, StopIteration):
        raise HTTPException(400, "Evento de prueba inválido")
    if (
        event.get("type")
        not in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }
        or obj.get("payment_status") != "paid"
    ):
        return {"processed": False}
    with closing(sqlite3.connect(root / "accounts.db", timeout=10)) as db, db:
        prepare(db)
        db.execute("BEGIN IMMEDIATE")
        order = db.execute(
            "SELECT account,plan,cents,session,paid FROM checkout_orders WHERE id=?",
            (obj.get("client_reference_id"),),
        ).fetchone()
        if not order:
            return {"processed": False}
        if not order[3]:
            raise HTTPException(503, "Orden pendiente de confirmación")
        if (
            order[3] != obj.get("id")
            or order[2] != obj.get("amount_total")
            or obj.get("currency") != "mxn"
            or obj.get("mode") != "payment"
            or obj.get("livemode") is not False
        ):
            raise HTTPException(400, "Los datos de pago no coinciden")
        inserted = db.execute(
            "INSERT OR IGNORE INTO stripe_events VALUES(?)", (event_id,)
        ).rowcount
        if not inserted or order[4]:
            return {"processed": False}
        db.execute(
            "UPDATE plans SET plan=?,expires=? WHERE account=?",
            (order[1], int(time.time()) + 30 * 86400, order[0]),
        )
        db.execute("UPDATE checkout_orders SET paid=1 WHERE session=?", (order[3],))
    return {"processed": True}
