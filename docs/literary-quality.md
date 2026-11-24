# Literary translation quality: implemented controls and evidence

## Scope

This change strengthens the existing Spanish-to-US-English pipeline. It does
not replace the model, send manuscripts to a new service, or claim that every
literary ambiguity is resolved. No manuscript excerpts are included in this
document or the new integration fixtures.

## Automatic behavior

- Validate the initial model output before accepting a segment. Empty output,
  copied Spanish, task envelopes, malformed function-word colons, unexpected
  JSON/code wrappers, unfinished colon fragments and broken name fragments
  trigger the existing bounded retry/rejection path.
- Preserve literal letter symbols and legitimate colons. Do not clean up a
  guessed remainder after a leaked prompt; retry the task instead.
- For general-purpose models, default to selective editorial review: no extra
  generative rewrite when there are no fidelity review candidates. A proposed
  revision must pass the surface checks, introduce no new consistency warnings,
  and leave no unresolved fidelity warnings before replacing the draft.
- Hy-MT2 retains its native translation profile and does not silently load a
  different model as a reviewer. Unresolved native translation risks remain
  visible to the existing review workflow.
- Flag bags/pockets in clothing and audible tinkling in a visual-light context.
  These are review candidates, never global word substitutions.
- Recognize explicit prevention governing coordinated English gerunds, reducing
  the false scope warning for constructions like "prevented ... from ...ing and
  ...ing". This recognizes one construction; it is not semantic certification.
- Very large length reductions are review warnings, not proof of omission.
- Reject malformed or explicitly unfinished Ollama response bodies.

## Persistence

Keep current checkpoint identities and preserve valid matching progress. Recheck
cached outputs before resuming; invalid cached pieces are retried. Recalculate
their fidelity warnings in memory. No checkpoint migration deletes old progress.

Read saved versions with current paragraph warnings only when their source and
target alignment is unambiguous. Do not rewrite their text, date or stored
warnings. An incomplete chapter cannot create a complete saved version; accepted
pieces remain available for the next attempt with the same identity.

## Editorial policy

The process environment variable `LIA_EDITORIAL_REVIEW_POLICY` accepts:

| Value | General-purpose-model behavior |
| --- | --- |
| `selective` (default) | Review drafts with fidelity candidates; retain draft if risks remain. |
| `off` | Retain the initial validated draft and its review warnings. |
| `always` | Legacy editorial-review mode with surface/consistency guards. |

Native Hy-MT2 bypasses generative editorial rewriting in all three modes. These
are developer controls; normal users do not need to configure them.

## Executed verification

Executed on 2026-11-24 with Python 3.12:

| Suite | Tests |
| --- | ---: |
| Provider profiles and fidelity warnings | 15 |
| Existing editorial guard regressions | 11 |
| Existing interruption/resume/identity regressions | 5 |
| New output validation and selective-review policy | 18 |
| API + real loopback HTTP transport + temporary SQLite | 7 |
| **Total** | **56 passed; 0 failures; 0 errors; 0 skipped** |

Compilation of the edited Python code also passed. The HTTP integration uses a
local fixture server returning synthetic model replies; it exercises the actual
urllib provider, translation pipeline, FastAPI routes, job completion and SQLite
code. It is not an Ollama inference test. The tests cover bounded retry,
incomplete-chapter rejection, recovery of only missing pieces, exact preservation
of tested paragraph separators, cached-output rejection and immutable versions.

`backend/tests/run_literary_quality.py` runs the suite and can write a JSON test
report. The accompanying GitHub Actions workflow is configured to run it on
relevant work-branch pushes and pull requests. Remote CI success must be checked
separately; the local execution above is the verified result.

## Limits of the evidence

The execution environment has no Ollama binary, model weights or reachable
Ollama service at localhost:11434. No real-model quality or speed measurement was
performed for this change. Windows/Flutter compilation was not performed.
Passing deterministic checks and having zero warnings do not establish literary
fidelity, fluent prose or publication readiness. They also do not establish that
this is the best available model or translation system.

The previously supplied model outputs remain evidence that quantities, causal
roles, negation and figurative language need bilingual evaluation. The next
quality decision must be based on real inference against held-out passages and
their intended meaning, not on warning counts or another unvalidated rewrite.
