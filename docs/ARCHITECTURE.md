# Architecture and experiment boundaries

Blackout Lab deliberately distinguishes three things: the commerce state, the response policy, and the independent verdict.

## Durable commerce state

Each service stores records under a random, immutable run ID. Reusing a checkout key within one run is an idempotent retry; using that key in another run is a separate experiment. Amounts are integer pretend cents, with a fixed price per unit. The API does not integrate a payment processor.

Orders first writes a durable intent. It then captures payment, reserves inventory and commits the order. These are separate transactions. The missing-order fault stops after the payment commit, leaving observable partial progress. Recovery can replay the intent because payment and reservation operations normally deduplicate by key. A key replay with a different quantity or amount is rejected.

Inventory uses an immediate SQLite transaction around stock and reservation changes. The duplicate-reservation fault intentionally bypasses its deduplication check. Recovery removes every extra reservation for a key and restores the corresponding units in the same transaction. Repeating this repair does not add stock again.

This is a small saga demonstration. It does not implement refunds or compensation for all possible failures, including out-of-stock after capture. Those are explicit future work rather than hidden assumptions.

## Transport and telemetry

`LocalTransport` calls the same service operations in one process. `HTTPTransport` sends JSON to independently running service processes. It does not automatically retry mutations. Orders uses the same transport for its downstream calls. The Compose deployment publishes only the control port to host loopback.

Domain spans include the run ID, laboratory correlation ID and OpenTelemetry trace ID. HTTP callers inject W3C context and service endpoints attach it before executing operations. Each service can export to a configured OTLP/HTTP collector. The local persisted event log is distinct from the optional collector backend.

## Response policy

Runbook is a reference baseline. It selects the authored plan for the known fault and makes no model calls.

Single-agent sends the evidence to one model call and executes its typed plan. Multi-agent sequentially runs commander, observer and investigator, passes their findings to the recovery specialist, executes its plan, and asks a verifier specialist to summarize the measured outcome. The model is shared; this is not independent model consensus.

The action vocabulary contains exactly five identifiers:

- `restore-orders`
- `restore-payments`
- `restore-inventory`
- `replay-checkouts`
- `deduplicate-inventory`

These map to known toy-service operations, never shell commands or model-selected addresses. Roles that only analyze cannot return actions. Schema-invalid outputs are rejected. Agents cannot choose another run or destination. Their evidence can contain untrusted text, and the policy boundary is the action schema plus fixed dispatch, not confidence in a prompt.

The scenario label, runbook and raw fault configuration are omitted from model snapshots. Fault-change events are omitted too. Operation failure text and invariant evidence can still reveal the cause. This introductory suite is not a blind root-cause benchmark.

## Verdict and persistence

Verification reads the stores through service APIs and checks actual ledgers. The narrative verifier cannot change check results. A fabricated "recovered" claim from any agent remains unresolved when invariants fail.

The control store persists lifecycle, events and final reports. The process owns a four-slot queue with two background workers; run one Uvicorn control worker. Restarting marks unfinished runs interrupted. This prototype does not automatically resume the agent hearing after a crash. Data grows until explicitly removed by the operator; no deletion endpoint is exposed.

## UI semantics

The dashboard polls control events incrementally by sequence and reads current state through the control API. It reports measured wall time, action count and invariant results. Replay animates the saved timeline; it does not rerun state mutations. The response strategy explicitly distinguishes runbook from model-backed runs. All dynamic evidence and model text use DOM text nodes, not HTML interpolation.

The server checks Host headers, rejects cross-origin writes, and serves a restrictive content security policy. These are supporting controls; the intended boundary remains a local development tool with no internet exposure and no real credentials.
