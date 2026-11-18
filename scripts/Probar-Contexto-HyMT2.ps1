param(
    [Parameter(Mandatory=$true)]
    [string]$ManuscriptPath,
    [string]$Model = 'lia-hymt2:1.8b-q8',
    [string]$OllamaUrl = 'http://127.0.0.1:11434'
)
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw "No se encontro Python: $Python" }
$TempScript = Join-Path ([IO.Path]::GetTempPath()) (('lia_contexto_' + [guid]::NewGuid().ToString('N')) + '.py')
if (-not (Test-Path -LiteralPath $ManuscriptPath -PathType Leaf)) { throw 'No existe el manuscrito elegido.' }
$Report = Join-Path $Repo ('logs\prueba_contexto_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.json')
$Prueba = @'
import json, re, time, uuid
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen

def load_cases(path):
    if path.suffix.lower() == ".docx":
        from docx import Document
        lines = [p.text.strip() for p in Document(str(path)).paragraphs if p.text.strip()]
    else:
        import html
        lines = [line.strip().rstrip(chr(92)).strip() for line in html.unescape(path.read_text(encoding="utf-8-sig")).splitlines() if line.strip()]
    patterns = [
        ("seleccion", r"lista de diez"),
        ("pregunta retorica", r"acaso.*no.*atrocidad"),
        ("quien controla", r"factores.*permitieron.*tenernos.*controlad"),
        ("negacion y accion", r"fuerza.*no.*decision|fuerza.*no.*decisi.n"),
        ("expresion figurada", r"pa.ses.*debajo del agua"),
        ("vestimenta", r"pantalones.*bolsas"),
        ("luz", r"luz.*tintineante"),
        ("equipo", r"sustancias.*vertidas.*bombas"),
    ]
    cases=[]
    for label, pattern in patterns:
        found=next((i for i,line in enumerate(lines) if re.search(pattern,line,re.I)),None)
        if found is None:
            print("No localizado:",label,flush=True)
            continue
        cases.append({"case":label,"source":lines[found],
                      "previous":lines[found-1][-650:] if found else "",
                      "following":lines[found+1][:650] if found+1<len(lines) else ""})
    if not cases:
        raise ValueError("No se localizaron pasajes de prueba en el archivo elegido")
    return cases


def extract(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("No se conservaron exactamente los marcadores")
    left = text.index(start) + len(start)
    right = text.index(end)
    if right <= left:
        raise ValueError("Marcadores fuera de orden")
    result = text[left:right].strip()
    if not result or len(result.splitlines()) != 1:
        raise ValueError("Salida vacia o estructura inesperada")
    return result

def call(source, model, base):
    prompt = ("Translate the following text into American English. Note that you should only output the translated result without any additional explanation:\n" + source)
    body = {"model": model, "stream": False, "raw": True,
            "prompt": "<\uff5chy_begin\u2581of\u2581sentence\uff5c><\uff5chy_User\uff5c>" + prompt + "<\uff5chy_Assistant\uff5c>",
            "options": {"num_ctx": 4096, "num_predict": 2048, "temperature": 0.3,
                        "seed": 42, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05,
                        "stop": ["<\uff5chy_EOT\uff5c>", "<\uff5chy_end\u2581of\u2581sentence\uff5c>"]}}
    req = Request(base.rstrip("/") + "/api/generate", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    before = time.monotonic()
    with urlopen(req, timeout=360) as response:
        result = json.load(response)
    raw = result.get("response")
    return raw, round(time.monotonic()-before, 2), result

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="lia-hymt2:1.8b-q8")
    p.add_argument("--url", default="http://127.0.0.1:11434")
    p.add_argument("--out", required=True)
    p.add_argument("--source", required=True)
    args = p.parse_args()
    records=[]
    out=Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print("Prueba comparativa: sin revision IA, sin cambios en SQLite ni versiones.", flush=True)
    print("Modelo:", args.model, "\nInforme:", out, flush=True)
    probe, seconds, meta = call("Mi hermana cerro la puerta y se fue.", args.model, args.url)
    print("CONTROL:", repr(probe), "Fin:", meta.get("done_reason"), "Tokens:", meta.get("eval_count"), flush=True)
    if not isinstance(probe, str) or not probe.strip() or meta.get("done_reason") == "length":
        out.write_text(json.dumps({"control": meta, "seconds": seconds}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit("Control fallido. No se ejecutan los 16 intentos. Comparte esta salida y el informe.")
    for case in load_cases(Path(args.source)):
        print("\n===",case["case"],"===\nORIGINAL:",case["source"],flush=True)
        for mode in ("aislado", "contexto_marcado"):
            record={**case,"mode":mode,"model":args.model}
            try:
                token=uuid.uuid4().hex[:12]
                start="[LIA_START_"+token+"]"
                end="[LIA_END_"+token+"]"
                source=case["source"] if mode=="aislado" else (case["previous"]+"\n\n"+start+"\n"+case["source"]+"\n"+end+"\n\n"+case["following"])
                raw,seconds,meta=call(source,args.model,args.url)
                record.update(raw=raw,seconds=seconds,done_reason=meta.get("done_reason"),tokens=meta.get("eval_count"))
                print("Fin:", meta.get("done_reason"), "Tokens:", meta.get("eval_count"), "Segundos:", seconds, flush=True)
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("Respuesta vacia. Metadatos: " + repr({k: v for k, v in meta.items() if k not in ("response", "context", "thinking")}))
                if meta.get("done_reason") == "length":
                    raise ValueError("Respuesta truncada por limite de tokens; se conserva la salida exacta en el informe")
                raw = raw.strip()
                translation=raw if mode=="aislado" else extract(raw,start,end)
                record.update(translation=translation,structure_valid=True)
                print(mode,seconds,"s:",translation,flush=True)
            except Exception as exc:
                record.update(structure_valid=False,error=str(exc))
                print(mode,"RECHAZADO:",exc,flush=True)
            records.append(record)
            out.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    print("\nTerminada. Marcadores validos NO certifican fidelidad. Comparar ambas variantes con el original.",flush=True)

if __name__ == "__main__":
    main()

'@
try {
    [IO.File]::WriteAllText($TempScript, $Prueba, (New-Object Text.UTF8Encoding($false)))
    $env:PYTHONUTF8 = '1'
    & $Python -u $TempScript --model $Model --url $OllamaUrl --out $Report --source $ManuscriptPath
    if ($LASTEXITCODE -ne 0) { throw 'La prueba no termino correctamente.' }
} finally {
    Remove-Item -LiteralPath $TempScript -ErrorAction SilentlyContinue
}
