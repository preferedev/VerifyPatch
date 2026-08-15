# VerifyPatch 0.2.0 User Manual

VerifyPatch is a command-line tool for Python repositories that use pytest. It compares two Git revisions, runs the repository's tests with Coverage.py, and reports whether changed executable lines are exercised by tests that the same pull request did not modify.

VerifyPatch does not require an AI model for its core analysis. It does not prove that a change is correct, identify who wrote a test, or sandbox the code it executes.

## The quickest useful run

Run VerifyPatch inside the virtual environment where your project and its test dependencies are installed:

```bash
python -m pip install verifypatch==0.2.0
git fetch origin main
verifypatch check --base origin/main --head HEAD
```

VerifyPatch writes two files in the current directory:

- `verifypatch.json`: the complete, schema-validated report and source of truth.
- `verifypatch.md`: a shorter report intended for people and CI summaries.

The repository needs two resolvable revisions and a clean tracked worktree. Commit or safely stash tracked changes before running it. Untracked files are not part of the compared Git revisions.

If VerifyPatch 0.2.0 has not been published to PyPI yet, install the locally built wheel instead:

```bash
python -m pip install /path/to/verifypatch-0.2.0-py3-none-any.whl
```

## What VerifyPatch measures

Every changed executable Python line is placed in exactly one partition:

| Partition | Meaning |
|---|---|
| `pr_untouched` | At least one covering test and its known applicable test infrastructure were not modified by the pull request. |
| `pr_touched_only` | The line was covered, but only by tests or known test infrastructure modified by the pull request. |
| `unknown_only` | Coverage occurred, but VerifyPatch could not safely attribute it to an exact test context. |
| `uncovered` | No observed test covered the changed executable line. |

“PR-untouched” describes Git provenance only. It does not mean a human wrote the test, that the test is trustworthy, or that the change is correct.

## Installation choices

### Core provenance only

```bash
python -m pip install verifypatch==0.2.0
```

This is enough for `check` and for a model-free `verify` run.

### Optional features

```bash
python -m pip install "verifypatch[openai]==0.2.0"
python -m pip install "verifypatch[anthropic]==0.2.0"
python -m pip install "verifypatch[generation]==0.2.0"
python -m pip install "verifypatch[mutation]==0.2.0"
python -m pip install "verifypatch[v2]==0.2.0"
```

| Extra | Adds |
|---|---|
| `openai` | Optional requirements extraction through the OpenAI API. |
| `anthropic` | Optional requirements extraction through the Anthropic API. |
| `generation` | Hypothesis-based generated tests from supported extracted requirements. |
| `mutation` | The optional Cosmic Ray backend. The built-in AST backend itself does not require this extra. |
| `v2` | All v2 provider, generation, mutation, and YAML dependencies. |

## `check`: the normal starting point

`check` is the stable schema-v1 provenance command:

```bash
verifypatch check \
  --base origin/main \
  --head HEAD \
  --root . \
  --pytest-args "-q" \
  --timeout 600 \
  --json-out verifypatch.json \
  --md-out verifypatch.md
```

Common comparisons:

```bash
# Current branch against the remote main branch
verifypatch check --base origin/main --head HEAD

# Last commit against its parent
verifypatch check --base HEAD~1 --head HEAD

# Two exact commits
verifypatch check --base <base-sha> --head <head-sha>

# A repository outside the current directory
verifypatch check --root /path/to/repository --base origin/main --head HEAD
```

Pass extra pytest options as one quoted string:

```bash
verifypatch check --base origin/main --head HEAD --pytest-args "-q -m 'not integration'"
```

Do not use pytest-xdist options such as `-n auto`; exact distributed test provenance is not supported in 0.2.0.

## Reading the result

Start with these JSON fields:

```text
status
coverage.changed_executable_lines
coverage.covered_by_pr_untouched_tests
coverage.covered_only_by_pr_touched_tests
coverage.covered_only_by_unknown_contexts
coverage.uncovered
coverage.pr_untouched_changed_line_coverage
findings
warnings
line_evidence
tests
```

Status meanings:

- `complete`: the requested analysis completed within the supported repository shape.
- `incomplete`: useful evidence exists, but some evidence could not be attributed safely.
- `error`: the analysis could not produce a trustworthy report.

A `null` ratio is not zero. It means the metric is not applicable or cannot be safely calculated, such as when there are no changed executable lines.

The findings section can flag changes such as newly skipped or xfailed tests, broad exception handlers, weakened assertions, reduced assertion counts, and removed tests. Findings request attention; they are not proof of wrongdoing.

## `verify`: the optional v2 pipeline

`verify` always emits schema v2. It includes the normal provenance run and can add requirements extraction, generated tests, mutation testing, behavioral comparison, and policy evaluation.

```bash
python -m pip install "verifypatch[v2]==0.2.0"
verifypatch verify --base origin/main --head HEAD
```

Without a `verifypatch.yml` file or command-line stage flags, the optional stages remain `not_requested`. This is intentional: network-backed and expensive stages do not turn themselves on.

Copy `verifypatch.example.yml` to `verifypatch.yml`, then enable only the stages you want.

### Model-free mutation example

This configuration needs no provider and no API key:

```yaml
version: 2

runtime:
  optional_timeout_seconds: 900
  artifacts_dir: .verifypatch/artifacts

requirements:
  enabled: false

generation:
  enabled: false

mutation:
  enabled: true
  backend: ast
  max_mutants: 50
  timeout_seconds: 600
  per_mutant_timeout_seconds: auto
  workers: 1
  operators:
    - comparison
    - boolean
    - arithmetic
    - constants

behavior:
  enabled: false

policy:
  incomplete: review
  minimum_pr_untouched_changed_line_coverage: null
  minimum_independent_mutation_score: null
  block_on_findings: []
  review_on_findings:
    - TEST_SKIP_ADDED
    - TEST_XFAIL_ADDED
    - ASSERT_TO_TRUTHY
```

Run it with:

```bash
verifypatch verify --base origin/main --head HEAD --config verifypatch.yml
```

The built-in `ast` backend is the honest default. To request Cosmic Ray explicitly:

```yaml
mutation:
  enabled: true
  backend: cosmic-ray
  fallback: null
```

Install `verifypatch[mutation]` first. A missing Cosmic Ray installation is reported as `missing_dependency`. VerifyPatch does not silently switch backends. Use `fallback: ast` only if that fallback is your explicit choice.

### Behavioral comparison example

Behavioral comparison calls an explicitly configured Python callable at the merge base and head revisions using the same JSON-compatible inputs:

```yaml
version: 2

behavior:
  enabled: true
  timeout_seconds: 180
  max_inputs_per_target: 20
  targets:
    - callable: mypackage.pricing:calculate_total
      inputs:
        - args: [100]
          kwargs: {discount: 0.1}
        - args: [0]
          kwargs: {}
      requirement_ids: []
```

Only configure deterministic, importable callables whose inputs and outputs can be serialized by the behavioral protocol. VerifyPatch executes the target repository; use an isolated disposable environment.

## Why OpenAI and Anthropic appear at all

They are used only by the optional **requirements extraction** stage. That stage reads allowlisted documentation, schemas, task files, and optional interface stubs from the merge-base revision and asks a configured model to convert source-backed statements into VerifyPatch's strict requirements schema.

Those extracted requirements can then feed the optional generated-test and behavioral stages. They do not replace pytest, coverage provenance, Git analysis, or mutation testing.

The normal flow is:

```text
Git diff + pytest + Coverage.py
            |
            +--> provenance report (no model required)

allowlisted merge-base documents
            |
            +--> optional OpenAI/Anthropic extraction
                         |
                         +--> structured requirements
                                      |
                                      +--> optional generated tests
                                      +--> optional behavior targets
```

If you do not need model-extracted requirements, leave `requirements.enabled: false`. VerifyPatch remains useful without OpenAI, Anthropic, Codex, Cursor, or any local model.

## Using OpenAI requirements extraction

Install the extra and supply an API key to the VerifyPatch process:

```bash
python -m pip install "verifypatch[openai]==0.2.0"
export OPENAI_API_KEY="your-api-key"
```

Choose the exact API model yourself; VerifyPatch never selects one automatically:

```yaml
version: 2

requirements:
  enabled: true
  provider: openai
  model: your-openai-model-id
  task_files:
    - docs/task.md
  base_sources:
    - README.md
    - docs/**/*.md
    - openapi.yaml
    - schemas/**/*.json
  minimum_confidence: high
  timeout_seconds: 90

generation:
  enabled: false
```

Then run:

```bash
verifypatch verify --base origin/main --head HEAD --config verifypatch.yml
```

The adapter uses the OpenAI Responses API structured-output interface. Provider refusal, malformed output, truncation, authentication failure, timeout, and citation mismatch remain incomplete/error evidence rather than becoming trusted requirements.

## Using Anthropic requirements extraction

```bash
python -m pip install "verifypatch[anthropic]==0.2.0"
export ANTHROPIC_API_KEY="your-api-key"
```

```yaml
version: 2

requirements:
  enabled: true
  provider: anthropic
  model: your-anthropic-model-id
  base_sources:
    - README.md
    - docs/**/*.md
    - schemas/**/*.json
  minimum_confidence: high
  timeout_seconds: 90
```

The Anthropic adapter uses the SDK's structured JSON-schema output interface. As with OpenAI, you must choose the model explicitly.

## Codex, Cursor, subscriptions, and local models

You can run VerifyPatch from a Codex or Cursor terminal exactly as you would from any terminal:

```bash
verifypatch check --base origin/main --head HEAD
```

You can also ask the coding agent to run VerifyPatch and summarize `verifypatch.json`. That does not mean VerifyPatch is calling the model behind the editor.

VerifyPatch 0.2.0 is a separate local Python process. It cannot automatically reuse:

- the model session currently answering inside Codex;
- a ChatGPT/Codex login or plan;
- Cursor's hosted model subscription or internal credentials; or
- a locally running Ollama, LM Studio, llama.cpp, or other model server.

For its optional provider stage, the shipped CLI recognizes only `provider: openai` and `provider: anthropic` and expects the corresponding SDK credentials in its process environment. A chat/editor subscription is not exposed to VerifyPatch as an API key.

Local and other hosted models are technically possible, but they are **not supported providers in 0.2.0**. Adding them correctly requires an adapter that:

- sends the exact extraction prompt and allowlisted merge-base sources;
- requests or enforces the requirements JSON schema;
- records the real provider and model;
- classifies refusal, truncation, timeout, malformed output, and dependency errors;
- validates every source citation and digest locally; and
- never silently changes provider or model.

An “OpenAI-compatible” endpoint is not automatically supported merely because it accepts similar HTTP requests; VerifyPatch currently depends on the official Responses API structured-output contract. Until a provider adapter and tests are added, use the model-free stages or one of the two shipped providers.

## Safely separating provider keys from untrusted tests

Never place an API key in the same CI job that runs pull-request code. Tests, `conftest.py`, imports, build hooks, and dependencies can read that job's environment.

Use the checked-in two-job example:

1. A trusted requirements job installs an exactly pinned VerifyPatch release in a neutral directory.
2. It reads only allowlisted merge-base inputs and creates a schema-validated requirements artifact.
3. It does not install or execute the pull-request repository.
4. A separate untrusted verification job downloads the artifact and runs pytest without provider credentials.

The first job can run:

```bash
verifypatch verify \
  --root /path/to/checked-out-repository \
  --base "$BASE_SHA" \
  --head "$HEAD_SHA" \
  --config /trusted/path/verifypatch.yml \
  --requirements-only \
  --json-out requirements-run.json \
  --md-out requirements-run.md
```

The second job uses the validated artifact with `--requirements-file` and receives no provider key.

See `examples/github-v2-two-job.yml` for the complete workflow. Use `pull_request`, not `pull_request_target`, and use ephemeral runners with read-only repository permissions.

## Generated tests

Generated tests require structured requirements and the `generation` extra. VerifyPatch 0.2.0 supports a deliberately narrow set of executable requirement kinds:

```text
bounds
charset
round_trip
idempotent
monotonic
non_negative
schema_valid
rejects_invalid
examples
```

Enable both extraction and generation:

```yaml
requirements:
  enabled: true
  provider: openai
  model: your-model-id

generation:
  enabled: true
  max_examples: 100
  deadline_ms: 200
  timeout_seconds: 180
  seed: 0
```

VerifyPatch compiles a constrained internal DSL into test files. It does not execute arbitrary Python supplied by the provider. Generated evidence remains a separate evidence class and never counts as PR-untouched.

## Policy and CI exit codes

Policy is always informational unless the command includes `--enforce`.

Example:

```yaml
version: 2

policy:
  incomplete: review
  minimum_pr_untouched_changed_line_coverage: 0.75
  block_on_findings:
    - TEST_REMOVED
  review_on_findings:
    - TEST_SKIP_ADDED
    - TEST_XFAIL_ADDED
    - ASSERT_TO_TRUTHY
  block_on_deleted_tests: true
  require_stages:
    - provenance
```

Informational run:

```bash
verifypatch verify --base origin/main --head HEAD --config verifypatch.yml
```

Enforced run:

```bash
verifypatch verify --base origin/main --head HEAD --config verifypatch.yml --enforce
```

Exit codes:

| Exit | Meaning |
|---:|---|
| 0 | Analysis completed; policy was absent, informational, or passed. |
| 2 | Invocation, repository, timeout, unsupported-condition, or analysis error. |
| 3 | `--enforce` was supplied and policy decided `block`. |

Null or incomplete metrics cannot satisfy configured numeric thresholds. Do not add `policy.mode`; it is obsolete and rejected.

You can reevaluate a saved report without rerunning tests:

```bash
verifypatch policy \
  --report verifypatch.json \
  --config verifypatch.yml

verifypatch policy \
  --report verifypatch.json \
  --config verifypatch.yml \
  --enforce
```

## GitHub Actions

For ordinary provenance, start from `examples/github-pull-request.yml`. A safe job should:

- trigger on `pull_request`, never `pull_request_target`;
- use `permissions: contents: read`;
- check out enough history to resolve both revisions;
- install the repository's dependencies;
- avoid secrets in the job that runs repository code;
- use an ephemeral GitHub-hosted runner and an explicit timeout; and
- upload the JSON and Markdown reports.

VerifyPatch is not a sandbox. Do not run untrusted pull requests on a reusable self-hosted runner unless it is strongly isolated and disposable.

## Repository configuration for `check`

The core command reads `[tool.verifypatch]` from your repository's `pyproject.toml`:

```toml
[tool.verifypatch]
test_paths = ["tests", "integration_tests"]
test_globs = ["checks/test_*.py"]
timeout_seconds = 900
omit = ["src/generated/**"]
```

VerifyPatch also respects the repository's Coverage.py configuration. Coverage exclusions and omitted files can change the executable-line denominator.

## Schemas and automation

Print bundled schemas without locating package files manually:

```bash
verifypatch schema report-v1
verifypatch schema report-v2
verifypatch schema requirements-v1
```

For automation, consume `verifypatch.json`, validate its `schema_version`, and treat the Markdown file as a presentation layer. `check` defaults to schema v1; `verify` emits schema v2.

## Troubleshooting

### `dirty tracked worktree`

VerifyPatch compares committed revisions. Commit or safely stash tracked changes, then rerun it.

### `invalid ref` or missing base revision

Fetch the base branch and enough history:

```bash
git fetch --no-tags origin main
git rev-parse origin/main
git rev-parse HEAD
```

In shallow CI clones, increase checkout depth or fetch the exact base SHA.

### `model_required`

Set `requirements.model` to an exact provider model ID. VerifyPatch deliberately does not choose one.

### `missing_dependency`

Install the extra for the requested stage. Examples:

```bash
python -m pip install "verifypatch[openai]==0.2.0"
python -m pip install "verifypatch[anthropic]==0.2.0"
python -m pip install "verifypatch[generation]==0.2.0"
python -m pip install "verifypatch[mutation]==0.2.0"
```

### `empty_context` or `unknown_only`

VerifyPatch observed coverage it could not attribute safely. Review collection-time imports, coverage concurrency, custom plugins, and unsupported distributed execution. The result stays conservative by design.

### xdist, tox, or nox

xdist provenance is unsupported. For tox or nox, enter or create a dedicated environment containing the project, pytest, and VerifyPatch, then invoke VerifyPatch from that exact interpreter without distributed pytest options.

### Tests fail during VerifyPatch

Run the equivalent pytest selection directly first:

```bash
python -m pytest -q
```

VerifyPatch records pytest outcomes, but a failing test run can make later optional stages skip or become incomplete. Inspect `tests`, `warnings`, and `pipeline.stages` in the JSON report.

## Operational checklist

Before relying on a report:

1. Confirm the base and head SHAs are the revisions you intended.
2. Run in an isolated environment containing the project's real test dependencies.
3. Keep secrets out of any process that imports or executes pull-request code.
4. Read `status`, warnings, null metrics, and stage errors before interpreting ratios.
5. Keep generated evidence separate from PR-untouched evidence.
6. Use `--enforce` only after agreeing on conservative policy behavior.
7. Retain the JSON report as the source of truth.
8. Remember that VerifyPatch reports observed evidence; it does not prove correctness or provide a sandbox.
