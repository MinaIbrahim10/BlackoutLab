# Live Ollama and DOM validation — 9 November 2026

## Scope and environment

Google Colab, Python 3.13, Tesla T4 (15 GiB), Ollama 0.40.15, `gemma4:e4b` (`dc35e8d9c606`, 6.6 GB download). Original source: `388104196b3245762f23605d68516d3a28e6ddb1` plus the integration changes in this branch. Ollama reported 100% GPU execution. Agent measurements followed an explicit warmup; initial GPU initialization was substantially slower than steady-state inference.

## Problems found and changes

Live testing exposed an analysis-role permission problem: the commander returned repair actions even though it was instructed not to. The runtime correctly rejected that answer, aborting the hearing rather than executing unauthorized actions. Analysis-role decoding schemas now constrain `actions` to an empty array, while recovery/single roles retain the five-action allowlist. The runtime permission check remains in place.

Requests now set `think: false` to allocate the bounded generation budget to the structured answer. Planning instructions also make explicit that restoring a service does not replay its durable intents, and repairing data does not disable an injected fault. These are descriptions of action semantics, not a hidden runbook fallback. The independently measured verdict is unchanged.

Colab also required `zstd` for the current official Ollama installer, and port 8080 was already occupied. The notebook supplies that dependency, uses port 8081, and allows only the exact generated Colab proxy hostname in addition to loopback hostnames. Package discovery is explicit so adding `notebooks/` does not make setuptools reject the distribution as multiple top-level packages.

## Measured recovery: do not select only the successful run

Each row is one trial per authored scenario. These are development runs used to diagnose and improve this tiny integration, not a held-out evaluation or statistical evidence that a strategy is superior.

| Stage | Surface | Runbook | Single | Multi |
| --- | --- | ---: | ---: | ---: |
| Original integration | CLI | 3/3 | 0/3 | 0/3 |
| JSON/role-schema fix | CLI | 3/3 | 2/3 | 3/3 |
| Same JSON/role-schema fix, separate fresh runs | HTTP API | 3/3 | Not measured | 0/3 |
| Final action-semantics clarification | CLI | 3/3 | 1/3 | 2/3 |
| Final action-semantics clarification, fresh runs | HTTP API | 3/3 | Not measured | 3/3 |

The final HTTP API outcomes are recorded in the raw `final/api-multi-*.json` reports. All outcomes, including unresolved cases, are retained. The apparent CLI success after the first fix did not reproduce across fresh API runs. Model-selected plans remain unreliable on this catalog; some omit required operations or select actions in an ineffective order even at temperature 0. Do not describe this release as a reliable incident-recovery agent or promise 100% AI recovery.

In final CLI runs, all 18 model calls completed with valid responses (three single calls plus five roles across three multi runs). Planning mistakes still produced failed actions or failed invariants. No automatic reference plan was substituted. An unresolved result is a successful enforcement of the evidence boundary, not successful recovery.

## Python, transport and DOM tests

- Python suite: 20/20 passed locally and in Colab, including real separate-process HTTP transport tests. The role-schema regression test checks analysis/recovery action permissions and explicit thinking control.
- Separate local reference benchmark: 9/9 recovered, zero model calls, all six checks passed.
- DOM integration against a real Python control server: all three runbook scenarios launched from the actual JavaScript UI and displayed 2 orders, 2 captures, stock 17 and 6/6 checks.
- Report downloads, history navigation/reopening, Field guide navigation and complete timeline replay were exercised.
- An unavailable Ollama endpoint produced a visible failed agent and unresolved run, zero executed recovery actions and no fallback.
- No JavaScript errors were observed in those DOM tests. Node 24/jsdom 31 is used; the test is configured in `DOM integration` CI. Inspect Actions for actual remote CI status.
- Cleaned combined notebook cells were syntax-checked. Equivalent operational commands ran in the saved Colab validation session; a separate fresh Run all of the cleaned repository notebook was not claimed.

## Remaining limitations

Visual browser QA is incomplete. Both servers started and responded to local HTTP requests inside Colab, but the cloud browser could not open the authenticated Colab port-proxy URL. DOM tests do not validate pixels, responsive rendering or real browser downloads. No public tunnel, disabled origin checks or public Ollama endpoint was introduced to work around that restriction.

GitHub's Compose job completed its configuration check, image build, health checks and distributed control API recovery exercise. External OTLP collector delivery was not newly validated. The older October validation record describes its own environment and should not be confused with this live Colab run.

Raw original, JSON-fix and final reports accompany this record under `docs/evidence/2026-11-09/`. Reports contain fake laboratory transactions and model-generated text. They do not establish production safety or factual accuracy of every explanation.

## Follow-up: bounded recovery and notebook UI

The recovery controller now returns actual post-action verification, execution errors, current evidence, and prior attempts to the single/recovery planner for up to three rounds. It stops on successful verification, inference failure, or budget exhaustion. No deterministic fallback is used. `--max-rounds 1` reproduces the previous budget. The legacy results above concern the one-shot controller and must not be presented as measurements of this revision.

The new local suites passed **47 tests and 2 subtests** in total. Coverage includes correcting an incomplete plan from real feedback, enforcing the attempt budget, preserving failed outcomes, and limiting the Colab callback to approved loopback lab API requests. Live Ollama measurements of this revision are pending. ThreadCourt has an isolated embedded evidence viewer with replay and a JSON download; BlackoutLab has a notebook callback transport for its real control UI. Both are included in the reusable notebook.

### Visual browser checks inside Colab

The in-notebook transport loaded the real BlackoutLab dashboard with `Lab connected`. All three runbook scenarios were launched by clicking the UI and recovered with six passing invariants (two orders, two captures, stock 17). Browser interactions verified run history, reopening evidence, the field guide and timeline replay. The evidence download produced a JSON report matching the selected recovered run.

ThreadCourt was rendered using the packaged viewer and the saved actual Gemma reports. Lost-update and lock-inversion both displayed the measured model outcomes; lock-inversion trace playback reached step 2 with row highlighting, and its evidence download produced the matching report. These checks cover the desktop Colab view; they do not establish mobile responsiveness or production safety.

The 47-test suite also passed on a fresh Colab T4 runtime, and both updated GitHub Actions suites passed. Both wheel packages built with the required viewer/module assets.

### Closed-loop live Ollama result

Fresh Colab T4 runtime, official Ollama 0.40.15, `gemma4:e4b` digest prefix `dc35e8d9c606`, temperature 0, thinking disabled, maximum three recovery rounds. All three scenarios were measured, three trials per AI mode, with no runbook fallback or discarded failures.

| Strategy | Recovered | Notes |
| --- | --- | --- |
| Runbook reference | 3/3 | One trial per scenario; no model calls |
| Single generalist | 6/9 | All three payment-outage trials remained unresolved after three rounds |
| Multi-role team | 9/9 | Two payment-outage trials required a second measured recovery round |

The multi-role team used five or six calls per run; the generalist used one or three. These are unequal inference costs, not a controlled equal-compute comparison. Nine successes do not guarantee future recovery. Model output cannot override the actual verifier. The three unresolved generalist reports are retained alongside successful runs.

A separate post-benchmark multi-agent payment-outage run launched through the real Colab UI was **unresolved (5/6 checks, three recovery rounds, seven calls)**. Thus the extra UI run must not be folded into a claim of universal 100% recovery; the combined multi-role observation is 9/10. The interface correctly surfaced the failure. Median benchmark latency was 5.42s for single and 17.79s for multi, excluding model warmup. A live UI metrics issue was also corrected: running experiments now count their own events instead of retaining previous-run action/call totals.

Full follow-up reports, including all failures, metadata and the experiment script, are retained in [BlackoutLab closed-loop evidence](https://github.com/MinaIbrahim10/BlackoutLab/tree/fix/ollama-colab-validation/docs/evidence/2026-11-09/closed-loop).
