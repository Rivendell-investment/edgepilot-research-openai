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

This Research surface never has account, credential, paper, exchange-demo, live execution
or order operations. If a requested operation is absent, explain the boundary; never route
through the Live profile or ask for a trading credential.

The local MCP route and bearer are created in an owner-private staged copy by the Runtime
Host. If the connection is unavailable, report that the Runtime/Host must be started
or repaired; do not search for Python, install packages, scan ports or call Marketplace MCP
as an internal substitute.
