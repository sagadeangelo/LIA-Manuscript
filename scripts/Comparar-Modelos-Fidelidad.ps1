param(
    [string]$InputReport = '',
    [string[]]$Models = @('qwen2.5:3b', 'mannix/llama3.1-8b-lexi:iq3_xs'),
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
$ReportDir = Join-Path $Repo ('logs\comparacion_modelos_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
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

def reviewer_task(warnings):
    guidance={
        "selection_quantity":"Identify how many people must be selected versus how many are on the list. Preserve the agent who supplies the list.",
        "rhetorical_negation":"Determine whether the Spanish is a negative rhetorical question or an expression of uncertainty. Preserve its communicative meaning.",
        "control_roles":"Identify who controls whom. Do not turn people being controlled into people controlling themselves.",
        "negation_scope":"Identify every coordinated action within the scope of negation. Do not turn a prevented action into an action performed.",
        "literal_idiom":"Resolve the expression using the political context; determine whether water is literal or figurative.",
        "ambiguous_equipment":"Resolve the equipment using the surrounding fluid-distribution context; distinguish a pump from an explosive bomb.",
    }
    return {
        "instruction":"Use the Spanish source as authority. The English draft may be wrong. Investigate each review candidate using context, correct only demonstrated errors, and return only the full translation of source in the translation field. Do not add explanations or facts. Candidates are hypotheses, not mandatory replacements.",
        "candidates":[{"code":w["code"],"check":guidance.get(w["code"],w.get("message","Check against source."))} for w in warnings],
    }

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
    if mode == "retranslate":
        # Blind to the flawed draft and issue labels: source and context only.
        return generate(item["source"], model, url, timeout=360,
                        structured_translation=True,
                        previous=item.get("previous","")[-650:],
                        following=item.get("following","")[:650])
    return generate(json.dumps({
        "source":item["source"],"draft":item["translation"],
        "review_task":reviewer_task(warnings),
        "previous_context":item.get("previous","")[-650:],
        "following_context":item.get("following","")[:650]},
        ensure_ascii=False), model, url, timeout=360,
        structured_translation=True,editorial_review=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['review','retranslate'],default='retranslate')
    p.add_argument('--repo',required=True);p.add_argument('--input',required=True)
    p.add_argument('--output',required=True);p.add_argument('--model',default='qwen3:4b')
    p.add_argument('--url',default='http://127.0.0.1:11434')
    a=p.parse_args()
    sys.path.insert(0,str(Path(a.repo)/'backend'))
    from app.services.providers.ollama_provider import generate
    from app.services.translation.translator import review_damage_reasons
    from app.services.translation.consistency_checker import check_consistency
    entries=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    if not isinstance(entries,list):raise SystemExit('El informe no contiene la lista de pruebas comparativas')
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    print('COMPARACION DE MODELOS. Modelo:',a.model,'Modo:',a.mode,flush=True)
    print('retranslate: Qwen recibe solo original y contexto; no ve el borrador ni los avisos.',flush=True)
    print('Sin glosario en esta prueba. Sin escritura en SQLite. Sin cambios en la app.',flush=True)
    for item in entries:
        if item.get('mode')!='aislado' or item.get('structure_valid') is not True:continue
        source=item['source'];draft=item['translation']
        warnings=diagnostic_warnings(source,draft,check_consistency)
        record={'case':item['case'],'source':source,'draft':draft,'warnings_before':warnings,'reviewer':a.model,'comparison_mode':a.mode}
        print('\n===',item['case'],'===',flush=True)
        print('ORIGINAL:',source,'\nBORRADOR:',draft,flush=True)
        if not warnings and a.mode != 'retranslate':
            record['status']='skipped_no_warning'
            print('SIN REVISION: no hay aviso heuristico. Esto no certifica fidelidad.',flush=True)
        else:
            print('AVISOS:',json.dumps(warnings,ensure_ascii=False),flush=True)
            before=time.monotonic()
            try:
                revised=request_proposal(generate,item,warnings,a.model,a.url,a.mode)
                record['proposal']=revised
                reasons,_,after=evaluate(source,draft,revised,review_damage_reasons,check_consistency)
                advisory=[reason for reason in reasons if reason.startswith('posible omision:')]
                if a.mode == 'retranslate':
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
    $Completed = 0
    foreach ($Model in $Models) {
        if ($Installed -notcontains $Model) {
            Write-Warning "Modelo no instalado: $Model. Se omite; no se descarga."
            continue
        }
        $SafeName = $Model -replace '[^a-zA-Z0-9._-]', '_'
        $OutputReport = Join-Path $ReportDir ($SafeName + '.json')
        Write-Host "`n=== MODELO: $Model ===" -ForegroundColor Cyan
        & $Python -u $TempScript --repo $Repo --input $InputReport --output $OutputReport --url $OllamaUrl --mode retranslate --model $Model
        if ($LASTEXITCODE -eq 0) { $Completed++ } else { Write-Warning "La prueba fallo para $Model. Se continua con el siguiente modelo." }
    }
    Write-Host "`nInformes: $ReportDir"
    if ($Completed -eq 0) { throw 'No se completo ningun modelo. Revisa los mensajes anteriores.' }
} finally {
    Remove-Item -LiteralPath $TempScript -ErrorAction SilentlyContinue
}
