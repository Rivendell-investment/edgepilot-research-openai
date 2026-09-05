---
name: edgepilot-research
description: Route anonymous public strategy discovery and reproducible historical backtests through the local EdgePilot Research Runtime. It has no accounts, credentials, paper, demo, live trading, or order execution.
---

# EdgePilot Research router

The Node Ready Bridge always exposes `edgepilot_runtime_status`,
`edgepilot_runtime_start`, `edgepilot_runtime_update` and `edgepilot_runtime_repair`, even
before Runtime exists. When Runtime is ready, use the five Host meta tools:

1. `edgepilot_connection_list`
2. `edgepilot_tool_search`
3. `edgepilot_tool_get`
4. `edgepilot_tool_execute`
5. `edgepilot_result_present`

Search for an operation, fetch its exact current descriptor, then execute with the returned
`schema_revision`. Do not invent dynamic tools, copy operation schemas into this plugin or
infer missing benchmark facts. Preserve exact strategy version, package digest,
configuration-schema digest, dataset provenance and Runtime identity in reproducible
results.

Route one user outcome at a time. Use `edgepilot_connection_list` for current anonymous
catalog availability. Search unknown capabilities once in concise English, batch Get for
the exact contracts, and batch Execute only for independent calls. A returned identifier or
digest starts a later dependency round. Present only an execute-minted `result_ref`.

The normal research route is catalog search/recommend, exact inspect/version list, install,
configuration resolve, backtest start, durable job status and result get. Runtime workflow
hints are navigation, not execution authority. Never repeat a start call merely because a
job is still queued or running.

For chat recommendation, call the read-only `edgepilot_strategy_recommend` convenience
tool with the structured questionnaire; it delegates to the Host operation
`catalog.strategy.recommend`. For “open Research”, call `edgepilot_dashboard_open` and
return its loopback URL; never start the Dashboard directly.

## First-use onboarding

Run this flow only when the user selects a setup/recommendation starter prompt or explicitly
asks for onboarding. Reply in the user's current language (`en`, `ko`, `zh-CN` or `zh-TW`).
Ordinary catalog, Dashboard, data or backtest requests go directly to that outcome and do
not force the questionnaire.

1. Call `edgepilot_runtime_status`. If it is `not_installed` or `stopped`, tell the user
   once that the anonymous Research Runtime will be downloaded or started, then call
   `edgepilot_runtime_start` exactly once. Never duplicate a slow start. On an error, report
   the stable error and stop; offer repair without silently running it.
2. Only after `state=ready` and `connection_ready=true`, call
   `edgepilot_dashboard_open` once and return its loopback URL.
3. Apply the **one-question turn boundary**. The internal field order is `profit_style`,
   `holding_period`, `pain_point`, `max_drawdown_pct`, `trading_mode`, `allocation_band`,
   `universe`. Ask only the first unanswered field, with only that field's choices, and end
   the assistant turn immediately. Never display the complete questionnaire, a numbered
   checklist, future questions, future choices or a request for multiple answers. Do not
   preview what comes next.
4. On the user's next message, retain every valid supplied answer and ask only the next
   unanswered field, then end the turn immediately again. If the current answer is invalid
   or ambiguous, clarify only the same field and end the turn; do not advance or expose any
   later field. A message that already contains valid answers may fill them silently, but
   the response still asks at most one unanswered field.
5. After the last answer, use a separate assistant turn to summarize the selected values
   and ask only for explicit confirmation. Do not combine that confirmation request with
   another question and do not call recommendation before confirmation.
6. Call `edgepilot_strategy_recommend` once with `questionnaire_version="2.0"`, the seven
   confirmed values and matching locale. Present exactly best fit, relatively steadier and
   more aggressive while preserving versions, evidence, trade-offs and warnings.

Do not install a recommended strategy until the user selects it. This flow remains anonymous
and never introduces an account, credential, paper, demo, live or order capability.

This Research surface never has account, credential, paper, exchange-demo, live execution
or order operations. If a requested operation is absent, explain the boundary; never route
through the Live profile or ask for a trading credential.

The local MCP route and bearer are created in an owner-private staged copy by the Runtime
Host. If the connection is unavailable, report that the Runtime/Host must be started
or repaired; do not search for Python, install packages, scan ports or call Marketplace MCP
as an internal substitute.
