# Validation record

Initial validation: 30 October 2026, Python 3.12, Linux development container.

## Completed locally

- `python -m pytest -q`: **20 passing tests**.
- All three authored scenarios fail at least one invariant before recovery and pass all six after the runbook.
- Nine measured reference runs (three per scenario): **9/9 recovered**, zero model calls, two recovery actions per run.
- See [runbook-reference.json](runbook-reference.json) for measured per-trial wall time and action counts. These are local development measurements, not AI performance claims.
- Duplicate checkout replay and concurrent same-key checkout attempts converge to one capture, order and reservation.
- Changed payloads under an existing idempotency key are rejected before another charge.
- Duplicate-reservation repair is itself idempotent; it does not restore extra stock when repeated.
- Run namespaces remain independent.
- Invalid action identifiers and invalid service faults are rejected.
- Model failure is recorded and does not activate a hidden runbook fallback.
- A mocked multi-agent hearing passes evidence between roles and executes its typed recovery plan.
- An agent claiming recovery without executing repairs cannot override failed invariants.
- The Ollama adapter's request schema and analysis-role action restriction are tested with mocked responses.
- API background execution, JSON download, incremental events, invalid IDs, startup interruption handling, cross-origin rejection and internal token checks are tested.
- **Real HTTP integration:** separate Orders, Payments and Inventory Uvicorn processes recover all three scenarios via `HTTPTransport`. Their spans contain nonzero OpenTelemetry trace IDs.
- `node --check blackout/static/app.js`: passed.
- A wheel builds and includes the packaged HTML, CSS and JavaScript.

## Not established locally

- **Live Gemma quality/latency:** no local Ollama model is available in this build environment. Mocked model results are not represented as real Gemma inference or comparative performance.
- **Docker runtime:** Docker is unavailable in this container. CI includes Compose configuration, build, health checks and end-to-end scenario execution on GitHub's Docker-enabled runner.
- **Visual/browser QA:** managed preview cannot execute the Python runtime. The API serves the dashboard assets successfully and JavaScript syntax passes, but visual appearance and interactive browser behavior are not claimed as verified.
- **OTLP collector delivery:** spans are produced; delivery to an external collector was not measured locally.

CI results are separate from this local record. The workflow runs the Python suite on 3.11–3.14 and a separate distributed Compose smoke job. Consult the repository's Actions tab for actual job outcomes.
