import os
import re
import secrets
import subprocess
import tempfile
import time
import urllib.request
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from contextlib import ExitStack

origin = "http://127.0.0.1:8133"
os.environ.update(
    STUDIO_ORIGIN=origin,
    STUDIO_DATA_DIR=tempfile.mkdtemp(),
    STUDIO_INVITE=secrets.token_urlsafe(32),
    STUDIO_LT_URL="http://127.0.0.1:8134",
)
with ExitStack() as stack:
    for cmd in [
        [
            "java",
            "-Xmx768m",
            "-cp",
            os.environ["LT_SERVER_JAR"],
            "org.languagetool.server.HTTPServer",
            "--port",
            "8134",
        ],
        [sys.executable, "-m", "uvicorn", "app.studio.server:app", "--port", "8133"],
    ]:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(p.terminate)
    for url in [origin + "/studio", "http://127.0.0.1:8134/v2/languages"]:
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.3)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_BINARY"), args=["--no-sandbox"]
        )
        for width in [1280, 390]:
            page = browser.new_page(viewport={"width": width, "height": 850})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(origin + "/studio")
            page.get_by_label("Correo electrónico").fill(f"demo-{width}@example.test")
            page.get_by_label("Contraseña", exact=True).fill(secrets.token_urlsafe())
            page.get_by_label("Invitación para crear una cuenta").fill(
                os.environ["STUDIO_INVITE"]
            )
            page.get_by_text("Crear cuenta", exact=True).click()
            page.get_by_label("Nombre del proyecto").fill("El reloj de papel")
            page.get_by_text("Crear proyecto", exact=True).click()
            expect(page.locator("#status")).to_have_text("Proyecto creado.")
            page.locator("input[type=file]").set_input_files(
                {
                    "name": "Reloj.txt",
                    "mimeType": "text/plain",
                    "buffer": "Capítulo I\nLa niña tienen un liibro.\nCapítulo II\nEl reloj canta.".encode(),
                }
            )
            page.get_by_text("Importar manuscrito", exact=True).click()
            expect(page.locator("#original")).to_contain_text("liibro")
            page.get_by_text("Analizar capítulo", exact=True).click()
            expect(page.locator("#findings article").first).to_be_visible(timeout=90000)
            row = (
                page.locator("#findings article")
                .filter(has=page.locator("strong", has_text="liibro"))
                .first
            )
            expect(row.get_by_text("Agregar al diccionario")).to_be_visible()
            row.get_by_text("Aplicar esta corrección").click()
            page.get_by_text("Guardar nueva versión").click()
            expect(page.locator("#book option")).to_have_count(2)
            assert "liibro" not in page.locator("#corrected").input_value()
            with page.expect_download() as download:
                page.get_by_text("Descargar EPUB").click()
            download.value.save_as(
                os.environ.get(
                    "STUDIO_TEST_EPUB",
                    str(Path(os.environ["STUDIO_DATA_DIR"]) / "prueba.epub"),
                )
            )
            if width == 1280 and os.getenv("STUDIO_TEST_MODEL") == "1":
                # Exercise translation of a short original passage, editorial revision, and handoff.
                page.locator("input[type=file]").set_input_files(
                    {
                        "name": "Lampara.txt",
                        "mimeType": "text/plain",
                        "buffer": "La lámpara dejó de brillar.".encode(),
                    }
                )
                page.get_by_text("Importar manuscrito", exact=True).click()
                expect(page.locator("#original")).to_have_text(
                    "La lámpara dejó de brillar."
                )
                page.get_by_text("Traducir capítulo", exact=True).click()
                expect(page.locator("#version option")).to_have_count(1, timeout=240000)
                assert page.locator("#translation").input_value().strip()
                page.locator("#translation").fill("The lamp stopped shining.")
                page.get_by_text("Guardar revisión del capítulo").click()
                expect(page.locator("#version option")).to_have_count(2)
                page.get_by_text("Preparar capítulo traducido en Publish").click()
                expect(page.locator("#original")).to_have_text(
                    "The lamp stopped shining."
                )
                print(
                    "PASS modelo real, versión traducida, revisión y envío a Publish",
                    flush=True,
                )
            page.locator("#layoutForm input[name=title]").fill("El reloj de papel")
            page.get_by_text("Guardar edición PDF", exact=True).click()
            expect(page.locator("#pdf")).to_have_attribute(
                "href", re.compile(r"interior\.pdf$")
            )
            proof = page.request.get(
                origin + page.locator("#pdf").get_attribute("href")
            )
            assert proof.ok and proof.body().startswith(b"%PDF-")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert not errors, errors
            page.get_by_text("Salir", exact=True).click()
            expect(page.locator("#access")).to_be_visible()
            page.close()
            print(
                "PASS Chromium",
                width,
                "registro, proyecto, TXT, capítulos, LanguageTool, versión, EPUB, logout",
                flush=True,
            )
