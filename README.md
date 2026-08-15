# VerifyPatch

VerifyPatch is CI for AI-written code that does not automatically trust AI-written tests.

It answers one question for every pull request:

> How much of this change is exercised by evidence the pull request did not also modify?

It does **not** prove that code is correct. It does not identify who originally authored historical tests. It does not certify human or agent independence. It observes Git provenance: which covering tests and known test infrastructure this pull request changed.

VerifyPatch executes untrusted repository code in the caller's environment. It is not a sandbox.

## Install

```text
pip install verifypatch==0.2.0
verifypatch check --base <ref-or-sha> --head HEAD
```

Optional extras are independently installable and do not pull unrelated extras:

```text
pip install "verifypatch[openai]"
pip install "verifypatch[anthropic]"
pip install "verifypatch[generation]"
pip install "verifypatch[mutation]"
pip install "verifypatch[v2]"
```

`python -m verifypatch` is equivalent to the `verifypatch` console script.

The command writes `verifypatch.json` (schema-validated) and `verifypatch.md`.

## Documentation

- [User manual](docs/USER_MANUAL.md)
- [Benchmarks](benchmarks.md)
- [GitHub pull-request workflow](examples/github-pull-request.yml)
- [Two-job v2 workflow](examples/github-v2-two-job.yml)

### CLI

```text
verifypatch check \
  --base <ref-or-sha> \
  --head <ref-or-sha> \
  --root <path> \
  --json-out verifypatch.json \
  --md-out verifypatch.md \
  --pytest-args "<args>" \
  --timeout <seconds>

verifypatch verify --base <ref-or-sha> --head HEAD --config verifypatch.yml
verifypatch policy --report verifypatch.json --config verifypatch.yml
verifypatch schema report-v1
verifypatch schema report-v2
verifypatch schema requirements-v1
```

`verifypatch check` is the backward-compatible provenance command and emits **schema v1**.
`verifypatch verify` runs the configured v2 pipeline and emits **schema v2**. Schema v2 is not the default for `check`.

Defaults:

- `--head HEAD`
- `--root` current directory
- `--json-out verifypatch.json`
- `--md-out verifypatch.md`
- `--pytest-args` empty
- `--timeout` 600 seconds (`[tool.verifypatch] timeout_seconds`)

Output directories are created if needed. Paths with spaces are supported.

Exit codes:

- `0` — requested analysis completed; policy is absent, informational, or passed
- `2` — invalid invocation, unsupported required condition, timeout, dirty tracked worktree, head mismatch, invalid refs, or analysis failure
- `3` — `--enforce` was supplied and policy decided `block`

Pytest's own exit code is recorded in JSON. VerifyPatch does not turn pytest failures into an undocumented merge gate. Policy remains informational unless `--enforce` is supplied. A `verifypatch.yml` `policy.mode` key is rejected; configuration cannot activate enforcement.

## What PR-untouched means

A covering test is **PR-untouched** when its test file and applicable known test infrastructure (root/nested `conftest.py`, shared helpers under configured test roots) were not changed by the pull request.

It does **not** mean:

- the test was written by a human
- the test is independent of an agent
- the production change is correct
- the pull request should merge

Lines covered by both PR-untouched and PR-touched tests count as PR-untouched. Coverage that cannot be mapped safely is **unknown**, never PR-untouched.

## Supported repository shape (v1)

- Python 3.10, 3.11, 3.12, 3.13, and 3.14 are validated. Newer CPython may work when dependencies support it.
- Git repository with resolvable base and head commits
- Conventional single-root pytest repository
- One non-xdist pytest process
- Python production files
- Test files under `tests/`, `test_*.py`, `*_test.py`, `conftest.py`, plus `[tool.verifypatch] test_paths` / `test_globs`

## Coverage configuration

VerifyPatch measures the same files Coverage.py would measure. It loads the customer's Coverage.py configuration (`.coveragerc`, `pyproject.toml`, `setup.cfg`, `tox.ini`) and uses Coverage.py's matchers and source analysis.

Documented Coverage.py precedence applies: when `source` or `source_pkgs` is set, `include` is not the outer bound of measurement. `omit` still excludes files. `exclude_lines`, `exclude_also`, and `# pragma: no cover` remove statements from the executable-line denominator.

A changed production file that Coverage.py omits is omitted from the denominator. A file must not disappear from the denominator because VerifyPatch misread `source = ["."]`, an importable module source, or `source` plus a non-matching `include`.

VerifyPatch overrides only what the v1 contract requires: isolated data file, relative filenames, line (not branch) coverage, a single process, and exact pytest node-ID contexts from its plugin.

## Unknown and incomplete reports

`status` is `complete` only when analysis is unambiguous within the supported contract. It is `incomplete` when usable results exist but certainty is incomplete, including:

- empty or unmapped coverage contexts
- coverage from import/collection time
- unsupported compatible concurrency
- test-file parse failure
- source-analysis failure

Unknown coverage stays `unknown_only` and never inflates PR-untouched counts. `status` is `error` when analysis cannot produce a report (the CLI then exits 2).

Zero changed executable lines produce a `null` coverage ratio in JSON and `n/a` in Markdown. Conservative incomplete results such as `empty_context` are not converted into confidence.

## Timeout

`--timeout` is a wall-clock limit on the pytest coverage subprocess. VerifyPatch starts that worker in its own process group, captures bounded stdout/stderr, and on expiry sends SIGTERM to the group, waits a short grace period, then SIGKILL. The same group cleanup runs on SIGTERM of VerifyPatch itself. On expiry VerifyPatch exits 2. It does not leave a successful complete report for a killed or timed-out run.

## GitHub Action

Use `pull_request`, never `pull_request_target`. Prefer ephemeral GitHub-hosted runners. VerifyPatch executes untrusted repository tests and is not a sandbox.

See `examples/github-pull-request.yml`. The sample workflow:

1. Checks out the pull request head SHA with enough history to resolve the base SHA
2. Sets up Python and installs the repository's own dependencies
3. Runs this composite Action, which installs VerifyPatch from the Action directory into the caller's Python and appends `verifypatch.md` to the job summary
4. Uploads `verifypatch.json` and `verifypatch.md` as artifacts
5. Uses `contents: read` only
6. Pins third-party Actions to immutable commit SHAs
7. Uses an ephemeral GitHub-hosted runner with a 30-minute timeout

Reusable self-hosted runners can be persistently compromised unless you isolate them. Do not pass repository secrets into the test job.

### Trusted two-job provider-key workflow

Provider credentials must never enter the job that executes untrusted head tests. The recommended workflow is `examples/github-v2-two-job.yml`:

1. `verifypatch-requirements` installs `verifypatch[openai]==0.2.0` into `${{ runner.temp }}`, treats the pull request checkout only as `--root` input data, and may use `OPENAI_API_KEY`
2. That job validates the artifact against the bundled schema and exact merge-base citation refs, paths, ordered line ranges, and range digests
3. `verifypatch-verify` installs `verifypatch==0.2.0` into a neutral directory, executes untrusted tests, and never receives provider secrets

Do not install the subject repository in the requirements job. Do not run VerifyPatch from the pull request working tree when a provider key is present.

## Unsupported (v1)

These produce a clear error or warning. They must not silently inflate PR-untouched coverage.

- pytest-xdist and distributed coverage (`-n auto`, `--numprocesses`, effective `--dist`; disabled forms such as `-n 0` and `--dist=no` are allowed)
- tox/nox matrices as the VerifyPatch runner
- Multiple independently configured pytest roots
- Cython/native/generated-source coverage
- subprocess/multiprocessing coverage unless already configured compatibly
- Hosted execution, LLM classification as a merge gate, Checks API merge gating

## v2 pipeline (opt-in)

`verifypatch verify` runs the v1 provenance check plus optional stages from `verifypatch.yml` (see `verifypatch.example.yml`):

```text
verifypatch verify --base <ref-or-sha> --head HEAD --config verifypatch.yml
```

`verifypatch.yml` is loaded with PyYAML (`pip install "verifypatch[v2]"` or PyYAML). Without a config file, optional stages stay `not_requested`.

The report is still not proof, certification, or a claim of agent independence. Generated tests are a third evidence class, never PR-untouched evidence. Independent Mutation Score is not a correctness score. No trust, safety, or certification score is produced.

The Anthropic extra pins the current 0.x SDK line (`anthropic>=0.121,<1`). Structured extraction uses the official `output_config.format` JSON Schema request shape. OpenAI uses the Responses API `text.format` JSON Schema shape. Model names are never chosen automatically.

Mutation testing defaults to the built-in `ast` backend. Cosmic Ray is used only when `mutation.backend: cosmic-ray` is set and `verifypatch[mutation]` is installed; a missing extra is reported as `missing_dependency` unless `mutation.fallback: ast` is set explicitly. Silent fallback is not allowed. The report records the effective backend and version. A mutant is scored only when applying it changes the semantic AST. Only pytest exit code 1 counts as a kill. Exits 0, 2, 3, 4, 5, and timeouts are not kills.

### tox / nox

VerifyPatch invokes pytest itself. Point it at an explicit interpreter and pytest command rather than hoping it discovers a tox/nox env:

```text
python -m verifypatch check --base origin/main --head HEAD --pytest-args "-q"
```

If tests only run inside tox, create a dedicated env that installs the project and call `verifypatch` from that env. Subprocess coverage is supported only when the repository already configures Coverage.py `concurrency = subprocess` compatibly; VerifyPatch warns instead of silently treating subprocess hits as PR-untouched evidence.

pytest-xdist remains unsupported until exact node-ID provenance survives combination of worker coverage data.

## Report

JSON (`verifypatch.json`) is the source of truth. Markdown is a derived view. There is no trust score, correctness certificate, evidence-strength label, or automatic merge recommendation.

Changed executable lines partition into:

- covered by PR-untouched tests
- covered only by PR-touched tests
- covered only by unknown contexts
- uncovered

Those four counts always sum to `changed_executable_lines`.

## Sample report

From the `discount` fixture (implementation change plus weakened tests):

```text
VERIFYPATCH
Independent Verification Report

Status: complete
Production files changed: 3
Tests changed by PR: 1
Changed executable lines: 8

PR-UNTOUCHED EVIDENCE

Changed lines covered by PR-untouched tests:
2 / 8
25.0%

PR-TOUCHED EVIDENCE

Changed lines covered only by PR-touched tests:
2 / 8
25.0%

TEST CHANGE ANALYSIS

Review findings: 3
Notice findings: 0
Tests skipped: 1

UNKNOWN EVIDENCE

Changed lines covered only by ambiguous contexts:
0 / 8
0.0%

UNCOVERED

4 / 8
50.0%

CAVEATS

- No correctness score or automatic recommendation was produced.
```

The four uncovered lines are the unimported `src/promo.py` module. Pricing changes are covered by untouched tests. Inventory changes are covered only by the PR-touched test file.

After this repository has at least two commits and a clean worktree, you can run VerifyPatch against itself:

```text
verifypatch check --base HEAD~1 --head HEAD
```

## License

Apache-2.0
