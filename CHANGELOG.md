# Changelog

## 0.2.0

Release of the v1 provenance checker plus the opt-in v2 verification pipeline.

### v1 provenance

- `verifypatch check` remains the backward-compatible command and emits report schema v1.
- Reports partition changed executable lines into PR-untouched, PR-touched, unknown, and uncovered evidence.
- Unknown and incomplete results stay conservative. `empty_context` and other incomplete reasons are never converted into confidence.
- Null coverage ratios stay null when the denominator is zero.

### v2 opt-in verification

- `verifypatch verify` emits report schema v2. Schema v2 is not the default for `check`.
- Optional stages (requirements, generated tests, mutation, behavioral replay) stay `not_requested` without configuration.
- Network-backed and expensive stages default to off. Environment variables supply secrets only and do not enable features.

### Policy

- Policy is informational unless `--enforce` is supplied.
- `--enforce` with a `block` decision returns exit code 3. `verifypatch policy` uses the same rule.
- `policy.mode` is not a configuration key. A file cannot mark policy as enforced.
- Ratio thresholds must be finite numbers in `[0.0, 1.0]`. Booleans, NaN, and infinities are rejected.
- Null or incomplete metrics cannot satisfy policy thresholds.

### Provider and mutation extras

- Optional extras are independently installable: `openai`, `anthropic`, `generation`, `mutation`, and `v2`.
- Anthropic extra: `anthropic>=0.121,<1`. OpenAI extra: `openai>=1.40`.
- OpenAI uses the Responses API `text.format` JSON Schema interface. Anthropic uses official `output_config.format`.
- Models are never selected automatically.
- Mutation defaults to the internal AST backend. Cosmic Ray runs only when configured and installed.
- Missing Cosmic Ray is `missing_dependency`. Silent fallback is not allowed; `mutation.fallback: ast` must be explicit.
- Mutants are applied only when the AST change is semantic. Only pytest exit code 1 can kill a mutant.

### Security model

- VerifyPatch executes untrusted repository code and is not a sandbox.
- Recommended GitHub workflows use `pull_request` (never `pull_request_target`), `contents: read`, ephemeral runners, and 30-minute timeouts.
- The two-job example installs `verifypatch==0.2.0` into a neutral directory, treats PR HEAD as `--root` data in the requirements job, and keeps provider keys out of the verification job.
- Artifact path traversal, forged citation refs/ranges/digests, and subject `sys.path` imports in requirements-only mode are rejected.
- Citation `digest` is the SHA-256 of the exact cited line range, not a whole-snapshot digest reused for an arbitrary subrange.
- SIGTERM and pytest timeout cleanup terminate the worker process group (children and grandchildren) after a SIGTERM grace period and SIGKILL escalation. v1 pytest output is byte-bounded.

### Compatibility

- Python 3.10–3.14.
- SPDX `Apache-2.0` metadata and license file.
- Repositories that set `filterwarnings = error` can collect and measure coverage without pytest assertion-rewrite failures from the VerifyPatch plugin.
- `check` stays schema v1 for the 0.2.x line. `verify` stays schema v2.

### Known conservative limitations

- pytest-xdist and distributed coverage remain unsupported.
- Some provenance trials may complete as `incomplete` (for example `empty_context`) rather than `complete`.
- Mutation scores are null when there are no valid executed mutants; zero-candidate cases are not reported as 0%.
- VerifyPatch does not prove correctness, trust, or human/agent independence.
