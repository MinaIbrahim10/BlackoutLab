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
