"""Run from backend with PYTHONPATH=. and Pandoc installed. All data is synthetic."""

import os
import secrets
import tempfile
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from fastapi.testclient import TestClient


def main():
    origin = "http://localhost:8129"
    with tempfile.TemporaryDirectory() as directory:
        os.environ.update(
            STUDIO_DATA_DIR=directory,
            STUDIO_ORIGIN=origin,
            STUDIO_INVITE=secrets.token_urlsafe(32),
        )
        from app.studio.server import app

        def run(size):
            client = TestClient(app, headers={"Origin": origin})
            response = client.post(
                "/api/register",
                json={
                    "email": f"libro-{size}@example.test",
                    "password": secrets.token_urlsafe(),
                    "invitation": os.environ["STUDIO_INVITE"],
                },
            )
            response.raise_for_status()
            project = client.post(
                "/api/projects", json={"name": "Demostración"}
            ).json()["id"]
            words = (
                "La tarde olía a lluvia y la calle guardaba silencio. ".split()
                * ((size + 9) // 10)
            )[:size]
            text = "\n".join(
                " ".join(words[start : start + 100]) for start in range(0, size, 100)
            )
            assert len(text.split()) == size
            start = monotonic()
            url = f"/api/projects/{project}/manuscripts"
            response = client.post(url, files={"file": ("Libro.txt", text.encode())})
            response.raise_for_status()
            imported = monotonic()
            book = url + "/" + response.json()["id"]
            epub = client.get(book + "/export/epub")
            epub.raise_for_status()
            assert (
                epub.content.startswith(b"PK")
                and client.get(book).json()["text"] == text
            )
            return (
                size,
                round(imported - start, 3),
                round(monotonic() - imported, 3),
                len(epub.content),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            print("palabras,importar_s,exportar_y_verificar_s,epub_bytes")
            for row in pool.map(run, [10000, 50000, 80000, 120000]):
                print(*row, sep=",")


if __name__ == "__main__":
    main()
