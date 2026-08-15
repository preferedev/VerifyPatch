# VerifyPatch 0.2.0 Benchmarks

This document contains reproducible release evidence and marketing-safe benchmark language for VerifyPatch 0.2.0. It is not a correctness, security, trust, or certification score.

- **Release commit:** `70d0b8794a3a495ebb199b6d9ba21d99e74cb906`
- **Benchmark date:** 2026-08-15
- **Benchmark system:** Apple M1 MacBook Air, 8 CPU cores, 8 GB RAM, macOS arm64
- **VerifyPatch version:** `0.2.0`

## Executive snapshot

- The default suite passed on every supported CPython version from 3.10 through 3.14: **210 passed, 1 optional skip, 2 live-provider tests deselected** on each version.
- Seven pinned open-source repository pairs were exercised for provenance analysis. Six completed; one returned a conservative `incomplete` result rather than overstating confidence.
- Three real repositories produced executable mutation candidates. All selected candidates were killed in this trial set, including kills attributable to PR-untouched tests. No survivor was produced, and no survivor claim is made.
- In a controlled three-repository comparison, median VerifyPatch provenance runs added **0.35 to 5.74 seconds** over plain pytest and approximately **47 to 48 MiB** of peak process-tree RSS.
- A synthetic schema-v1 report with **50,000 line-evidence rows** produced 10.34 MB of JSON and passed schema validation in approximately **1.09 seconds**.
- The wheel is approximately **95 KiB**, has no mandatory provider or mutation dependencies, and passed isolated installation and Twine checks.

These results describe the tested repositories, commits, environments, and configurations below. They are measured examples, not universal runtime or defect-detection guarantees.

## Release-validation matrix

The default suite was run with live-provider tests deselected. The one skip is the intentional Cosmic Ray `importorskip` in environments without the mutation extra.

| Python | Result |
|---|---:|
| 3.10.20 | 210 passed, 1 skipped, 2 deselected |
| 3.11.15 | 210 passed, 1 skipped, 2 deselected |
| 3.12.13 | 210 passed, 1 skipped, 2 deselected |
| 3.13.13 | 210 passed, 1 skipped, 2 deselected |
| 3.14.4 | 210 passed, 1 skipped, 2 deselected |

Cosmic Ray 8.7.0 integration: **4 passed**.

Independent installations of the base package and `[openai]`, `[anthropic]`, `[generation]`, `[mutation]`, and `[v2]` extras all passed `pip check`. Optional packages did not leak into unrelated extras.

## Real-repository provenance trials

These are pinned base/head comparisons. `Complete` means VerifyPatch completed its declared analysis; it does not mean the patch was proven correct.

| Repository | Changed executable lines | PR-untouched coverage | Runtime | Status |
|---|---:|---:|---:|---|
| iniconfig | 8 | 100% | 1.89 s | complete |
| idna | 3 | 100% | 9.23 s | complete |
| tomli-w | 0 | n/a | 2.08 s | complete |
| zipp | 1 | 0% | 1.79 s | complete |
| tomli | 1 | n/a | 1.82 s | incomplete (`empty_context`) |
| pluggy | 3 | 100% | 2.10 s | complete |
| packaging | 0 | n/a | 11.64 s | complete |

The `tomli` result is deliberately reported as incomplete: an ambiguous or empty coverage context is not converted into PR-untouched evidence. Zero changed executable lines remain `n/a`, not 0%.

Pinned comparisons:

| Repository | Base SHA | Head SHA |
|---|---|---|
| iniconfig | `6d0af4529e4375e49dc871aa3d5ce17fe1791afe` | `58c08691bbb86aee8efbf73e37293dd6d65b68b4` |
| idna | `f39ea903ba49eb5a0b2c6723c9a929b41ed4a0f1` | `9067b803a55441805934410b11c0899209b66785` |
| pluggy | `237edb6e8e3067c46f91ae620a652e2fb20bf68e` | `54127a334d52a49d02c77b001ee998d36f7d6037` |

The complete seven-repository provenance manifest, including the remaining pinned SHAs and evidence partitions, is maintained with the release-validation records.

## Plain pytest versus VerifyPatch

### Method

- Three measured runs per command; table reports the median wall-clock time.
- Plain pytest and `verifypatch check` ran in the same prepared repository environment.
- Peak RSS is the sampled sum of the command's process tree, not just the parent CLI.
- `PYTHONPATH` was empty and user site packages were disabled.
- Repositories were local and warm; dependency installation and clone time were excluded.
- These small suites make fixed startup and coverage costs prominent. The ratio should not be extrapolated to large suites.

| Repository | Plain pytest median | VerifyPatch median | Added time | Runtime multiple | Plain peak RSS | VerifyPatch peak RSS | Added peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| iniconfig | 0.233 s | 0.579 s | 0.346 s | 2.48x | 43.8 MiB | 90.6 MiB | 46.8 MiB |
| idna | 2.746 s | 8.488 s | 5.742 s | 3.09x | 94.3 MiB | 141.9 MiB | 47.7 MiB |
| pluggy | 0.332 s | 0.869 s | 0.538 s | 2.62x | 46.9 MiB | 94.9 MiB | 48.0 MiB |

**Marketing-safe summary:** In three pinned Python repositories, VerifyPatch added 0.35–5.74 seconds over plain pytest while collecting changed-line coverage provenance. Peak process-tree memory increased by approximately 47–48 MiB in these runs.

## Mutation evidence

The internal AST backend was used. Only pytest exit code 1 counts as a kill; collection errors, internal errors, usage errors, interruption, and timeout do not increase the kill count.

| Repository | Candidates | Selected | PR-untouched kills | Other outcomes | Independent score | Overall score |
|---|---:|---:|---:|---|---:|---:|
| iniconfig | 3 | 3 | 3 | 0 survivors | 1.000 | 1.000 |
| idna | 3 | 3 | 1 | 2 PR-touched kills, 0 survivors | 0.333 | 1.000 |
| pluggy | 3 | 3 | 3 | 0 survivors | 1.000 | 1.000 |
| zipp / tomli | 0 | 0 | n/a | no candidates | n/a | n/a |

This trial set demonstrates candidate discovery, semantic application, test-origin attribution, and conservative zero-candidate handling. It does **not** establish a general mutation score, and it produced no genuine survivor to showcase.

## Large-report scaling

Synthetic schema-v1 reports used one `LineEvidence` object per changed executable line, all classified as PR-untouched. Each measurement ran in a fresh Python 3.13.13 process. Times are single local measurements.

| Evidence rows | JSON size | JSON serialization | Schema validation | Peak process RSS |
|---:|---:|---:|---:|---:|
| 1,000 | 206,602 bytes | 0.003 s | 0.028 s | 31.5 MiB |
| 10,000 | 2,060,605 bytes | 0.023 s | 0.213 s | 38.1 MiB |
| 50,000 | 10,340,605 bytes | 0.130 s | 1.093 s | 78.6 MiB |

The Markdown summary remained under 1 KiB because it reports aggregate coverage rather than repeating every line-evidence row. JSON remains the complete machine-readable source of truth.

## Output-boundary stress check

VerifyPatch returns at most 64,000 bytes from each bounded subprocess output stream. Both a 1 MiB and a 32 MiB stdout producer returned exactly 64,000 bytes with `truncated: true`.

| Child output | Returned output | Duration | Peak caller RSS |
|---:|---:|---:|---:|
| 1 MiB | 64,000 bytes | 0.030 s | 25.1 MiB |
| 32 MiB | 64,000 bytes | 0.110 s | 134.0 MiB |

Important limitation: clipping occurs after `communicate()` receives the stream, so the current implementation bounds reported output but not peak buffering memory. Do not market this as a subprocess memory limit.

## Heuristic-rule conformance

A balanced, hand-authored micro-corpus exercised the six shipped test-change finding types plus benign edits:

- 9 positive cases: skip decorator/call, xfail decorator/call, bare or `Exception` handler, equality-to-truthiness weakening, test removal, and assertion-count drop.
- 9 negative cases: unchanged test, specific exception, assertion addition, equality value change, test addition, conservative single rename, pre-existing skip, non-test function, and class test unchanged.
- Result: **18/18 exact expected finding sets**.

This is rule conformance, not a real-world precision/recall study. It is safe to say the shipped rules detected their designed trigger cases without firing on the listed benign controls. It is not safe to publish an “accuracy” percentage.

## Interruption and cleanup evidence

Recorded release gates sent SIGTERM during v1 pytest/coverage, generated-test execution, mutation execution, and behavioral replay. All four recorded:

- process exit 143;
- no surviving ordinary child or grandchild processes;
- no tracked-file modifications;
- no leftover `verifypatch-mut-*` or `verifypatch-behavior-*` directories;
- no partially trusted success report; and
- `cleanup_ok: true`.

An additional adversarial check deliberately created a child that called `setsid()` and retained inherited output pipes. That detached child escaped process-group termination and could delay output collection until its pipe closed. The exact test process was removed and a final process-table check found no survivor. VerifyPatch is not a sandbox; deliberately detached descendants remain a known limitation.

## Distribution artifacts

| Artifact | Size | SHA-256 |
|---|---:|---|
| `verifypatch-0.2.0-py3-none-any.whl` | 97,600 bytes | `06642d2afdd4377ce229f0ce07228369def43e49327a786e1798351182ec3357` |
| `verifypatch-0.2.0.tar.gz` | 108,356 bytes | `f2dce540b8aad6e7ffd9d1cc0d84cd780fb54c1549e396b1f97295b664638df1` |

Both artifacts passed `twine check`. The wheel was installed from a neutral directory and passed `pip check`, CLI help, bundled-schema loading, schema-v1 `check`, schema-v2 `verify`, and enforced-policy exit-code smoke tests. Rebuilt artifacts may have different hashes; publish the hashes of the exact files uploaded.

## What remains unverified

- Live OpenAI and Anthropic API requests: SDK request shapes and failure modes are tested, but no provider credentials were available for live calls.
- Windows execution: release validation covers macOS locally and targets Linux in CI, but no Windows runner result is recorded.
- A consumer repository using the final tagged composite Action: static workflow tests and local fixture smoke passed, but no external tagged run exists before the tag is published.
- Fork-pull-request behavior of the two-job provider workflow: the secret boundary is statically validated, but no end-to-end fork trial is recorded.
- Real-world heuristic precision/recall, broad ecosystem compatibility, and universal performance guarantees.

## Approved website copy

### Short proof bar

> Validated on Python 3.10–3.14 with 210 default tests per version, seven pinned open-source provenance trials, real mutation runs, isolated package-extra installs, and clean wheel installation.

### Performance copy

> On three pinned Python repositories, VerifyPatch added 0.35–5.74 seconds over plain pytest while collecting changed-line test provenance. Measured peak process-tree memory increased by about 47–48 MiB.

### Product copy

> VerifyPatch separates changed lines covered by PR-untouched tests from evidence introduced or modified in the same pull request. Ambiguous evidence stays unknown or incomplete instead of being promoted to confidence.

### Required qualifier

> VerifyPatch reports observed test evidence and provenance. It executes repository code, is not a sandbox, and does not prove correctness, authorship, or independence of the people or agents involved.

## Claims to avoid

Do not claim that VerifyPatch:

- proves a patch is correct, safe, secure, or independently authored;
- has a measured bug-detection or false-positive rate;
- supports every pytest repository, operating system, monorepo, xdist, tox, or nox configuration;
- bounds subject-process memory or contains malicious code;
- has live-validated provider integrations until credentialed smoke tests are recorded; or
- is faster or more accurate than another product without a controlled comparative study.

## Reproduction notes

For comparable measurements, use the exact release artifact, immutable repository SHAs, isolated environments, an empty `PYTHONPATH`, disabled user-site packages, and at least three measured runs after environment setup. Report medians, retain raw samples, include host specifications, and distinguish plain test runtime from cloning and dependency installation. Never convert `incomplete`, zero-candidate, or null metrics into successful percentages.
