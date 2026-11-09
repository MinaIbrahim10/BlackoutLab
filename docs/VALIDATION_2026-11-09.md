# Validation status — 9 November 2026

## Current implementation

BlackoutLab grounds planning in actual failed service operations, validates nonempty evidence and executable plans, and returns measured post-action feedback for at most three recovery rounds. Analysis roles cannot issue actions. Invalid structured output and model-server HTTP 5xx responses receive at most one correction/retry per role call; every rejected attempt remains in the report. Connection failures and HTTP 4xx responses are not retried. There is no reference-runbook fallback. The independent invariant checker determines recovery.

The control queue allows four outstanding incidents and executes one incident at a time. The shared Ollama client also serializes inference calls. The mobile navigation remains available at a 390px embedded width. Colab uses a narrow, authenticated notebook callback to the loopback API; no public tunnel or exposed model endpoint is required. Rerunning setup updates existing checkouts, and the dashboard cell restarts its previous notebook-owned server.

## Verified automated checks

The combined local Python suites passed 54 tests and 2 subtests during development (41 BlackoutLab, 13 ThreadCourt). For application commit `bec2a93a520bf3912620821f4b423ec0420c10db`, GitHub Actions independently passed Python 3.11–3.14, frontend/Compose and DOM integration. Both cleaned notebooks pass Python-cell syntax validation. A separate fresh Run all of the cleaned notebook has not been claimed.

## Live Colab observations

Environment: Python 3.13, Tesla T4 15 GiB, official Ollama 0.40.15, `gemma4:e4b` digest prefix `dc35e8d9c606`, thinking disabled and temperature 0. These are development runs on three authored scenarios, not held-out evaluation or equal-compute strategy comparisons.

| Development phase | Single recovered | Multi recovered | Observed failure |
| --- | ---: | ---: | --- |
| Earlier bounded feedback controller | 6/9 | 9/9 | Three unresolved payment incidents; a separate Multi UI run also remained unresolved |
| Grounded operation evidence, CLI | 15/15 | 15/15 | One verifier inference failed after recovery; separate UI run returned empty plans and remained unresolved |
| Required executable plan, HTTP API | 9/9 | 6/9 | Three invalid structured recovery answers |
| One format correction, HTTP API | 3/3 | 5/6 | One Ollama HTTP server error |
| Serialized queue/client plus bounded HTTP 5xx retry | **Not yet reverified** | **Not yet reverified** | Last six-run API batch and extra UI run were launched; final results could not be retrieved after Google sign-in expired |

The grounded CLI phase used source `d9ecb6ca4583876d982b0228eda9742e930a4125`; required-plan API used `190d38d85ade76d22396ee39c230152e74d2f0f7`; format-correction API used `3d754c4a48f8128019eb8cee9f1c0d8edfffaad8`. The pending final live check used `bec2a93a520bf3912620821f4b423ec0420c10db`. Do not attribute earlier successful measurements to that final revision or infer future 100% model reliability.

Browser checks exercised all three Runbook scenarios, history/reopening, field guide, timeline replay and matching JSON download. Later actual phone-width AI checks recovered payment Multi, missing-order Single and duplicate-inventory Single, each with 6/6 invariants. Another inventory Multi UI run recovered after one rejected structured response and its correction. Empty-plan and unresolved outcomes were displayed rather than concealed. The latter run took roughly 104 seconds under concurrent development workloads, exposing the need for queue/client serialization.

## Evidence and outstanding retrieval

[Earlier full report history](VALIDATION_2026-11-09_EARLIER.md) and [exported raw reports](evidence/2026-11-09/) retain previous failures as well as successes. The later grounded/required-plan/correction phase counts above are recorded from the live validation session; their additional raw Colab files have not yet been exported to this repository. Final live batch results and those raw files still require the authenticated Colab session. This is an explicit validation gap, not a successful final live test.

The notebook itself is reusable; Colab compute and the live dashboard require a connected runtime. External OTLP collector delivery was not newly validated. All transactions are synthetic laboratory data.
