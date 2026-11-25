"""Snapshot and restore an offline staging data directory into a new private directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_checked(source, destination, restore):
    if (
        destination.exists()
        or source in destination.parents
        or not (source / "accounts.db").is_file()
    ):
        raise ValueError("Indica un origen de Studio y un destino nuevo fuera de él")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        output = Path(staging) / "data"
        output.mkdir(mode=0o700)
        expected = json.loads((source / "snapshot.json").read_text()) if restore else {}
        manifest = {}
        for path in sorted(
            [source / "accounts.db", *source.glob("*/lia_manuscript.sqlite3")]
        ):
            rel = str(path.relative_to(source))
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("Origen inválido")
            if restore and expected.get(rel) != checksum(path):
                raise ValueError("Copia incompleta o alterada")
            target = output / rel
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if restore:
                shutil.copyfile(path, target)
            else:
                source_db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                destination_db = sqlite3.connect(target)
                try:
                    source_db.backup(destination_db)
                finally:
                    destination_db.close()
                    source_db.close()
            os.chmod(target, 0o600)
            db = sqlite3.connect(target)
            try:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Falló la verificación de integridad")
                if restore and rel == "accounts.db":
                    db.execute("DELETE FROM sessions")
                    if db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='mail_tokens'"
                    ).fetchone():
                        db.execute("DELETE FROM mail_tokens")
                    db.commit()
            finally:
                db.close()
            manifest[rel] = checksum(target)
        if restore and set(manifest) != set(expected):
            raise ValueError("Faltan archivos en el respaldo")
        if not restore:
            (output / "snapshot.json").write_text(json.dumps(manifest, indent=2))
        output.rename(destination)
    print(f"Bases verificadas: {len(manifest)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    copy_checked(
        args.source.resolve(), args.destination.resolve(), args.action == "restore"
    )
