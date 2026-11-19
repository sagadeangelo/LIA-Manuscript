param(
    [string]$InputReport = '',
    [string]$Model = 'qwen2.5:3b',
    [string]$OllamaUrl = 'http://127.0.0.1:11434'
)
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw "No se encontro Python: $Python" }
if (-not $InputReport) {
    $Latest = Get-ChildItem -LiteralPath (Join-Path $Repo 'logs') -Filter 'prueba_contexto_*.json' -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Latest) { throw 'No se encontro informe de contexto. Indica -InputReport.' }
    $InputReport = $Latest.FullName
}
$ReportDir = Join-Path $Repo ('logs\diagnostico_formato_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
$Installed = @((Invoke-RestMethod ($OllamaUrl.TrimEnd('/') + '/api/tags') -TimeoutSec 15).models | ForEach-Object { $_.name })
$TempScript = Join-Path ([IO.Path]::GetTempPath()) ('lia_selectiva_' + [guid]::NewGuid().ToString('N') + '.py')
$Prueba = @'
import argparse,json,re,sys,time
from pathlib import Path


def diagnostic_warnings(source, target, checker):
    warnings=list(checker(source,target))
    if re.search(r"\bpantalones\b",source,re.I) and re.search(r"\bbags?\b",target,re.I):
        warnings.append({"code":"clothing_polysemy","message":"Check pockets versus bags and singular versus plural referents using context."})
    if re.search(r"\bluz\b.*tintineante",source,re.I) and re.search(r"\b(?:tinkling|chime-like)\b",target,re.I):
        warnings.append({"code":"visual_polysemy","message":"Check visual flickering versus an audible tinkling sound."})
    return warnings

def proposal_status(reasons, after):
    if reasons:
        return "rejected_keep_draft"
    if after:
        return "unresolved_keep_draft"
    return "candidate_manual_comparison"


def evaluate(source,draft,revised,damage,checker):
    reasons=list(damage(draft,revised,source))
    if not revised.strip() or len([x for x in revised.splitlines() if x.strip()]) != 1:
        reasons.append('Estructura vacia o multilinea')
    words=re.findall(r'[^\W\d_]+',revised.casefold())
    es=set('el la los las de del que en una por para con sus esta este pero porque fue eran como donde'.split())
    en=set('the of and in to was were with from for that this it they had their but as on'.split())
    if words==re.findall(r'[^\W\d_]+',source.casefold()) or sum(w in es for w in words)>=max(4,2*sum(w in en for w in words)+2):
        reasons.append('Copia del original o probable salida en espanol')
    before=diagnostic_warnings(source,draft,checker);after=diagnostic_warnings(source,revised,checker)
    old_codes={w['code'] for w in before}
    if any(w['code'] not in old_codes for w in after):
        reasons.append('Nuevo aviso de consistencia')
    return reasons,before,after


def request_proposal(generate, item, warnings, model, url, mode):
    if mode == "direct":
        prompt = ("Translate the following Spanish text into natural American English. "
                  "Preserve all facts, actions, negations, quantities and names. "
                  "Output only the complete translation, without explanations.\n\n" + item["source"])
        return generate(prompt, model, url, timeout=360)
    return generate(item["source"], model, url, timeout=360,
                    structured_translation=True,
                    previous=item.get("previous","")[-650:] if mode == "json_context" else "",
                    following=item.get("following","")[:650] if mode == "json_context" else "")


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['direct','json_no_context','json_context'],default='direct')
    p.add_argument('--repo',required=True);p.add_argument('--input',required=True)
    p.add_argument('--output',required=True);p.add_argument('--model',default='qwen3:4b')
    p.add_argument('--url',default='http://127.0.0.1:11434')
    a=p.parse_args()
    sys.path.insert(0,str(Path(a.repo)/'backend'))
    from app.services.providers import ollama_provider as provider
    generate=provider.generate
    from app.services.translation.translator import review_damage_reasons
    from app.services.translation.consistency_checker import check_consistency
    import io
    from unittest.mock import patch
    transport=provider.request.urlopen
    audit=[]
    def audited_transport(req, **kwargs):
        body=json.loads(req.data) if req.data else {}
        if req.full_url.endswith('/api/generate'):
            body.setdefault('options',{}).update(temperature=0,num_ctx=4096,num_predict=2048,seed=42)
            req=provider.request.Request(req.full_url,data=json.dumps(body).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
        with transport(req,**kwargs) as response:
            raw=response.read()
        if req.full_url.endswith('/api/generate'):
            audit.append({'request':body,'response':json.loads(raw)})
        return io.BytesIO(raw)
    def controlled_generate(*args, **kwargs):
        with patch.object(provider.request,'urlopen',side_effect=audited_transport):
            return generate(*args,**kwargs)
    entries=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    if not isinstance(entries,list):raise SystemExit('El informe no contiene la lista de pruebas comparativas')
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    print('COMPARACION DE MODELOS. Modelo:',a.model,'Modo:',a.mode,flush=True)
    print('Formato:',a.mode,'Sin borrador ni avisos en la solicitud.',flush=True)
    print('Parametros iguales: temperature=0, seed=42, context=4096, output=2048.',flush=True)
    print('El informe local incluye solicitudes y respuestas exactas. No se publican.',flush=True)
    print('Sin glosario en esta prueba. Sin escritura en SQLite. Sin cambios en la app.',flush=True)
    for item in entries:
        if item.get('mode')!='aislado' or item.get('structure_valid') is not True:continue
        source=item['source'];draft=item['translation']
        warnings=diagnostic_warnings(source,draft,check_consistency)
        record={'case':item['case'],'source':source,'draft':draft,'warnings_before':warnings,'reviewer':a.model,'comparison_mode':a.mode}
        print('\n===',item['case'],'===',flush=True)
        print('ORIGINAL:',source,'\nBORRADOR:',draft,flush=True)
        print('AVISOS:',json.dumps(warnings,ensure_ascii=False),flush=True)
        audit.clear()
        before=time.monotonic()
        try:
            revised=request_proposal(controlled_generate,item,warnings,a.model,a.url,a.mode)
            record['proposal']=revised
            reasons,_,after=evaluate(source,draft,revised,review_damage_reasons,check_consistency)
            advisory=[reason for reason in reasons if reason.startswith('posible omision:')]
            reasons=[reason for reason in reasons if reason not in advisory]
            record.update(warnings_after=after,rejection_reasons=reasons,length_advisories=advisory,
                          status=proposal_status(reasons,after))
            print('PROPUESTA QWEN:',revised,flush=True)
            print('AVISOS DESPUES:',json.dumps(after,ensure_ascii=False),flush=True)
            print('RESULTADO:',record['status'], '; '.join(reasons),flush=True)
            if advisory: print('AVISO DE LONGITUD (no prueba omision):', '; '.join(advisory),flush=True)
        except Exception as exc:
            record.update(status='error_keep_draft',error=str(exc))
            print('ERROR:',exc,flush=True)
        record['transport_audit']=list(audit)
        record['seconds']=round(time.monotonic()-before,2)
        print('SEGUNDOS:',record['seconds'],flush=True)
        records.append(record)
        output.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    if not records:raise SystemExit('No se encontraron borradores aislados validos en este informe')
    from collections import Counter
    print('\nRESUMEN:',dict(Counter(r['status'] for r in records)),flush=True)
    print('TIEMPO TOTAL DE SOLICITUDES:',round(sum(r.get('seconds',0) for r in records),2),'s',flush=True)
    print('\nINFORME:',output,flush=True)
    print('Una propuesta sin rechazos sigue siendo candidata: requiere cotejo de significado. No se guardaron traducciones.',flush=True)

if __name__=='__main__':main()

'@
try {
    [IO.File]::WriteAllText($TempScript, $Prueba, (New-Object Text.UTF8Encoding($false)))
    $env:PYTHONUTF8 = '1'
    if ($Installed -notcontains $Model) { throw "Modelo no instalado: $Model" }
    $Completed = 0
    foreach ($Format in @('direct','json_no_context','json_context')) {
        $OutputReport = Join-Path $ReportDir ($Format + '.json')
        Write-Host "`n=== FORMATO: $Format | MODELO: $Model ===" -ForegroundColor Cyan
        & $Python -u $TempScript --repo $Repo --input $InputReport --output $OutputReport --url $OllamaUrl --mode $Format --model $Model
        if ($LASTEXITCODE -eq 0) { $Completed++ } else { Write-Warning "Fallo el formato $Format." }
    }
    Write-Host "`nInformes: $ReportDir"
    if ($Completed -eq 0) { throw 'No se completo ningun formato.' }
} finally {
    Remove-Item -LiteralPath $TempScript -ErrorAction SilentlyContinue
}

