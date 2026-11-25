from io import BytesIO
import importlib
import secrets
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient


def test_private_editorial_flow(tmp_path, monkeypatch):
    origin = "http://localhost:8129"
    invitation = secrets.token_urlsafe(32)
    monkeypatch.setenv("STUDIO_ORIGIN", origin)
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUDIO_INVITE", invitation)
    server = importlib.import_module("app.studio.server")
    monkeypatch.setattr(server, "root", tmp_path)
    a = TestClient(server.app, headers={"origin": origin})
    b = TestClient(server.app, headers={"origin": origin})
    assert a.get("/api/projects").status_code == 401
    for client, email in [(a, "a@example.test"), (b, "b@example.test")]:
        credentials = dict(
            email=email, password=secrets.token_urlsafe(), invitation=invitation
        )
        assert client.post("/api/register", json=credentials).status_code == 201
        assert client.post("/api/logout").status_code == 200
        assert client.post("/api/login", json=credentials).status_code == 200
    assert (
        a.post(
            "/api/projects",
            json={"name": "Libro"},
            headers={"origin": "https://example.test"},
        ).status_code
        == 403
    )
    project = (
        "/api/projects/" + a.post("/api/projects", json={"name": "Libro"}).json()["id"]
    )
    assert b.get(project).status_code == 404
    doc = Document()
    for line in ("Capítulo I", "La puerta cantaba.", "Capítulo II", "Nadie volvió."):
        doc.add_paragraph(line)
    stream = BytesIO()
    doc.save(stream)
    uploaded = a.post(
        project + "/manuscripts", files={"file": ("obra.docx", stream.getvalue())}
    )
    assert uploaded.status_code == 201
    book = project + "/manuscripts/" + uploaded.json()["id"]
    assert b.get(book).status_code == 404
    assert (
        b.get(
            book + "/translation-progress/00000000-0000-0000-0000-000000000000"
        ).status_code
        == 404
    )
    assert len(a.get(book + "/chapters").json()) == 2
    changed = a.post(
        book + "/corrected",
        json={"chapter": 0, "text": "Capítulo I\nEl reloj cantaba.\n"},
    )
    assert changed.status_code == 201
    new = project + "/manuscripts/" + changed.json()["id"]
    assert "El reloj" in a.get(new).json()["text"]
    assert "La puerta" in a.get(book).json()["text"]
    assert "Nadie volvió." in a.get(new).json()["text"]
    for fmt, member in [("docx", "word/document.xml"), ("epub", "mimetype")]:
        out = a.get(new + "/export/" + fmt)
        assert out.status_code == 200
        with ZipFile(BytesIO(out.content)) as archive:
            assert member in archive.namelist()
            assert archive.testzip() is None
            if fmt == "epub":
                assert archive.infolist()[0].filename == member
                assert archive.read(member) == b"application/epub+zip"
        assert b.get(new + "/export/" + fmt).status_code == 404
    from uuid import uuid4

    layout = a.post(
        new + "/layouts",
        json={
            "title": "El reloj",
            "trim": "a5",
            "margin": 18,
            "dedication": "Para Mara.",
        },
    )
    assert layout.status_code == 201
    pdf_url = new + "/layouts/" + layout.json()["id"] + "/interior.pdf"
    pdf = a.get(pdf_url)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert b.get(pdf_url).status_code == 404
    assert len(a.get(new + "/layouts").json()) == 1
    order = {"plan": "staylo", "event": str(uuid4())}
    assert a.post("/api/subscription/simulate", json=order).json()["activated"]
    assert not a.post("/api/subscription/simulate", json=order).json()["activated"]
    assert (
        a.post(
            "/api/subscription/simulate", json={**order, "plan": "publish"}
        ).status_code
        == 409
    )
    assert a.get(book + "/export/epub").status_code == 403
    assert a.get("/api/admin/summary").status_code == 403
    admin = secrets.token_urlsafe(40)
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", admin)
    summary = a.get(
        "/api/admin/summary", headers={"Authorization": "Bearer " + admin}
    ).json()
    assert summary["accounts"] == 2 and summary["simulated_events"] == 1
    assert "La puerta" not in str(summary)
    # Exercise Stripe's test protocol with a synthetic provider response and a signed payload.
    import hashlib, hmac, json, time
    from app.studio import checkout

    test_secret = "whsec_" + secrets.token_hex(24)
    monkeypatch.setenv("STUDIO_STRIPE_TEST_WEBHOOK", test_secret)
    monkeypatch.setenv("STUDIO_STRIPE_TEST_KEY", "sk_test_" + secrets.token_hex(12))
    session_id = "cs_test_" + secrets.token_hex(12)

    class Provider:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "livemode": False,
                "id": session_id,
                "url": "https://example.test/checkout",
            }

    monkeypatch.setattr(checkout.httpx, "post", lambda *args, **kwargs: Provider())
    order_id = str(uuid4())
    assert (
        a.post(
            "/api/checkout", json={"plan": "publish", "order_id": order_id}
        ).status_code
        == 200
    )
    obj = {
        "mode": "payment",
        "livemode": False,
        "currency": "mxn",
        "amount_total": 1000,
        "payment_status": "paid",
        "client_reference_id": order_id,
        "id": session_id,
    }
    body = json.dumps(
        {
            "id": "evt_demo",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": obj},
        }
    ).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        test_secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    webhook = "/webhooks/stripe-test"
    assert a.post(webhook, content=body).status_code == 400
    headers = {"Stripe-Signature": f"t={stamp},v1={signature}"}
    assert a.post(webhook, content=body, headers=headers).json()["processed"]
    assert not a.post(webhook, content=body, headers=headers).json()["processed"]
    assert a.get("/api/subscription").json()["plan"] == "publish"
    assert a.post(book + "/review", json={"text": "Libro"}).status_code == 403
    assert (
        a.post(
            "/api/subscription/simulate", json={"event": str(uuid4()), "plan": "studio"}
        ).status_code
        == 200
    )
    assert (
        a.post(book + "/dictionary", json={"word": "Palabraficticia"}).status_code
        == 201
    )
    assert a.post("/api/logout").status_code == 200
    assert a.get(book).status_code == 401
    from app.studio import mail

    received = {}
    monkeypatch.setenv("STUDIO_SMTP_HOST", "test.invalid")
    monkeypatch.setenv("STUDIO_MAIL_FROM", "pruebas@example.test")
    monkeypatch.setattr(
        mail,
        "send_link",
        lambda email, purpose, token: received.update({purpose: token}),
    )
    email = "correo@example.test"
    old = secrets.token_urlsafe()
    new = secrets.token_urlsafe()
    profile = {"email": email, "password": old, "invitation": invitation}
    assert a.post("/api/register", json=profile).json()["verification_required"]
    assert a.get("/api/projects").status_code == 401
    assert (
        a.post(
            "/api/mail/request", json={"email": email, "purpose": "verify"}
        ).status_code
        == 202
    )
    assert (
        a.post("/api/mail/redeem", json={"token": received["verify"]}).status_code
        == 200
    )
    assert (
        a.post("/api/mail/redeem", json={"token": received["verify"]}).status_code
        == 400
    )
    assert a.post("/api/login", json=profile).status_code == 200
    assert (
        a.post(
            "/api/mail/request", json={"email": email, "purpose": "reset"}
        ).status_code
        == 202
    )
    assert (
        a.post(
            "/api/mail/redeem", json={"token": received["reset"], "password": new}
        ).status_code
        == 200
    )
    assert a.get("/api/projects").status_code == 401
    assert a.post("/api/login", json=profile).status_code == 401
    assert a.post("/api/login", json={**profile, "password": new}).status_code == 200


def test_dialogue_attribution_from_cpu_evaluation():
    from app.services.translation.output_quality import output_issues

    source = "—No abras la ventana —susurró Mara."
    assert "misplaced_dialogue_quotes" in output_issues(
        source, """Don't open the window, "Mara whispered. " """
    )
    assert not output_issues(source, '"Don’t open the window," Mara whispered.')
