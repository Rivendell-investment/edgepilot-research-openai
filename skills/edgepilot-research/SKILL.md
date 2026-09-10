---
name: edgepilot-research
description: Route anonymous public strategy discovery and reproducible historical backtests through the local EdgePilot Research Runtime. It has no accounts, credentials, paper, demo, live trading, or order execution.
---

# EdgePilot Research router

The Node Ready Bridge always exposes `edgepilot_runtime_status`,
`edgepilot_runtime_start`, `edgepilot_runtime_update` and `edgepilot_runtime_repair`, even
before Runtime exists. The bridge automatically prepares the release-bound Runtime before first business use; never treat an older compatible Runtime as ready. When Runtime is ready, use the five Host meta tools:

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

1. Call `edgepilot_runtime_status`, then `edgepilot_runtime_start` when the bound target
   needs starting, installation or recovery. Let the script decide whether to reuse,
   start, prepare or resume; do not infer process liveness from stored job states or
   historical lifecycle phases and do not assemble alternative shell recovery commands.
   Wait for the original call's final result; yielded/running is not completed. If the
   script reports `runtime_operation_pending`, wait on that call or query status with
   bounded backoff, without parallel open calls or duplicate installations.
   When `state=awaiting_confirmation`, show `switch.processes` and `switch.jobs` and ask
   once: “暂不切换” (`defer`) or “停止旧版本并继续” (`stop_and_continue`), translated into
   the user's language. Explain that stopping trading programs does not guarantee order
   cancellation or position closure. Submit the chosen action to the same lifecycle tool
   with the returned `operation_id` and `snapshot_digest`; never invent or reuse a changed
   snapshot. This choice authorizes only the listed process stop, not an orders/positions
   review. A refreshed snapshot requires a fresh choice. On `deferred`, end this target
   startup request and leave the old environment alone; do not open old onboarding as
   target success. Report other failures and their script-provided recovery action.
   For `stale_session`, reload the plugin session rather than attempting a downgrade.
2. For this Dashboard-and-onboarding request, all successful paths (already running,
   stopped target started, first installation, upgrade or repair) continue identically.
   Only after `state=ready` and `connection_ready=true`, call
   `edgepilot_dashboard_open` once and return its loopback URL. Then call
   `edgepilot_onboarding_open` once with the current locale. On success, hand control to
   that interactive card and end the turn. A brief instruction to continue in the card is
   enough; do not repeat questionnaire choices in chat or call another question/selection
   tool. Keep all seven choices, review and recommendation inside that one App.
   The tool does not report rendering visibility. Missing model-visible HTML, missing
   acknowledgement or delayed rendering is unknown, not evidence of failure. Never claim
   the card did not appear based on that absence and never automatically start text onboarding
   alongside a successful App request. Do not restart installation to recover presentation.
3. Switch to text onboarding only when the host explicitly reports App rendering unsupported
   or failed, or the user reports the card unusable or explicitly requests text onboarding.
   A Runtime/tool execution error follows step 1 recovery, not the questionnaire fallback.
   Apply the **one-question turn boundary**
   as the formal fallback. The internal field order is `profit_style`,
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
6. In the textual fallback, call `edgepilot_strategy_recommend` once with `questionnaire_version="2.0"`, the seven
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

## Upgrade recovery

The plugin ships its fixed-release lifecycle entry. Upgrades are forward-only; do not invoke
rollback or search for system Python. Inspect a pending lifecycle operation instead of starting
a duplicate. Active backtests or writes must complete or be explicitly cancelled before upgrade.
Research never uses Live task management or reads Live state.
