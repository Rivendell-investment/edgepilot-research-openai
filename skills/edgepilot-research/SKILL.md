---
name: edgepilot-research
description: Discover public market strategies, install reviewed research packages, run offline or public-data historical backtests, and explain reproducible research results. Use only for research and backtesting; it has no accounts, credentials, paper, demo, live trading, or order execution workflow.
---

# EdgePilot Research

## Local MCP and Dashboard lifecycle

The bundled local stdio MCP completes protocol startup without starting the
loopback Research Dashboard. Discovery and three-card recommendations do not
require that server or the native runtime. Use `open_dashboard` to start or
reconnect to the Dashboard and obtain its real URL; never assume port 8686 or
start a second server.

On the first user-visible reply after EdgePilot Research is selected in a new ChatGPT conversation, explain in the user's current language that the local Research Dashboard starts on first open, is reachable only on this device, and normally stops when ChatGPT closes or the plugin is disabled. Offer long-term background operation only as an explicit later choice. Do not claim that the Dashboard is already running before `open_dashboard` succeeds.
<!-- CODEX_ACTIVATION_START -->
Before the first preference question, call the read-only `verify_activation` tool. If it reports `activation: "ready"`, ask the first question in the same reply. If it reports `restart_required`, explain that a verified Research Dashboard from another plugin version is still running and ask the user to restart Codex, then continue in a new task. Never infer activation from a PID, process name, port scan, or plugin files alone.

For install or upgrade, inspect the candidate package's bundled Dashboard before replacing files:

```bash
python3 skills/edgepilot-research/scripts/stop_local_dashboard.py --stop-if-running
```

```bat
py -3 skills\edgepilot-research\scripts\stop_local_dashboard.py --stop-if-running
```

The helper returns `not_running` for a fresh install, stops only the bundled Dashboard whose private record and health nonce agree, and refuses when the stop handshake cannot be verified. When it returns `not_running` or `stopped`, install the files and use the host's task-creation capability when available to create and start a fresh Codex task with the documented first-use prompt; the installation request is explicit authorization for that action. Do not use task handoff, which moves an existing task without creating a fresh MCP/tool context. If task creation is unavailable, ask the user to create the task and provide the prompt for copying. Restart Codex only if a verified old Dashboard remains, the new task does not expose the installed MCP, or `verify_activation` reports a version mismatch. Never kill Python by name or PID alone, and never remove Research runtime or user state during plugin activation.
<!-- CODEX_ACTIVATION_END -->
Only after that product-specific request and explicit tool confirmation, use
`enable_persistent_dashboard`; disclose
`capital.rivendell.edgepilot.research.dashboard` (Windows:
`\EdgePilot\Research Dashboard`). For “恢复 EdgePilot Research 随 Codex 运行”,
confirm and use `disable_persistent_dashboard`. Never change the Live service.

## First-run strategy guidance

Treat `Help me choose a strategy` and `Show me the available strategies` as onboarding routes, not one-shot answers. Reply in the user's current conversation language. If the user changes language, switch immediately without discarding confirmed answers. Keep offering one concrete next action until the user chooses an exact strategy version, ends the flow, or a real capability boundary prevents the handoff. Do not check the runtime, request login, download a package, or install anything while the questionnaire is incomplete.

Start with a short, naturally translated welcome carrying this meaning: EdgePilot Research helps clarify a strategy idea and test it with historical data; it can help choose when the user has no direction or help test an existing idea. Chinese wording is only an example, never a fixed response for every language.

For `Help me choose a strategy`, immediately begin the existing V2 questionnaire. Ask one unanswered question at a time, using three localized choices and mapping only unambiguous answers to these canonical values in order:

1. `profit_style`: `trend | reversal | relative_value`
2. `holding_period`: `intraday | multi_day | multi_week`
3. `pain_point`: `loss_streak | inactivity | tail_loss`
4. `max_drawdown_pct`: `5 | 15 | 20`
5. `trading_mode`: `long_only_no_leverage | long_short_low_leverage | long_short_high_leverage`
6. `allocation_band`: `under_25k | 25k_100k | over_100k`
7. `universe`: `majors | altcoins | any`

Reuse answers already clear from the conversation and ask the user to choose among the current three options when meaning is ambiguous. After all seven answers, show a localized summary and accept an optional note of at most 500 Unicode code points for user review only. Do not send the note, free text, derived fields, custom weights, or unknown fields to the recommendation tool. Map locale to `en`, `ko`, `zh-CN`, or `zh-TW`; for other languages keep conversing in that language, submit `locale=en`, and disclose that strategy names or summaries may fall back to English.

When the bundled `recommend_strategies` MCP tool is available, call it with only `questionnaire_version: "2.0"`, the seven confirmed canonical answers, and `locale`. Using that tool is required because its structured result is bound to the ChatGPT recommendation-card UI. Do not replace it with a direct HTTP or CLI request. Accept only a complete three-card response with distinct slugs and the unchanged roles and order `best_fit`, `safer`, `more_aggressive`. Preserve the top-level recommendation identity, versions, snapshot, normalized profile, candidate and exclusion counts, and `fallbacks`. For every card preserve the exact `slug`, `version`, `preset`, `role`, `match_score`, `score_breakdown`, `strategy_profile`, `evidence`, `matched_reasons`, `tradeoffs`, and `warnings`; translate controlled explanations without changing their meaning. Never score, rank, fill, reorder, replace, or relax constraints. Keep the text fallback concise when ChatGPT renders the cards. On `CATALOG_COVERAGE_INSUFFICIENT`, rate limiting, network failure, or a partial response, explain the failure and do not fabricate a recommendation.

If the current surface does not expose `recommend_strategies`, preserve and summarize the canonical answers, explain that this surface can browse the anonymous Research catalog but cannot render the formal three-card match, and offer continued catalog exploration. Guide the user to **Find the right strategy** only when a current Research Dashboard or generated launcher is already available. Never install or check the native runtime merely to obtain a recommendation. Do not require login, silently switch to the Live product, claim a formal recommendation, or reproduce the scoring algorithm.

For `Show me the available strategies`, immediately query the anonymous Research catalog without checking or installing the runtime. On a fresh plugin with no generated launcher, use an available network-capable tool to GET `https://edge-pilot.rivendell.capital/api/research/strategies?sort=published&limit=5&locale=LOCALE` directly; never install the runtime merely to obtain the CLI. If the launcher already exists, its `marketplace search` command remains valid. Show at most five items in default published order with name, summary, assets, timeframes, risk profile, and available annualized return, maximum drawdown, and Sharpe. If any of those three benchmark metrics is `null`, label the benchmark unavailable rather than inferring it. End the list with localized actions to filter by asset/category/risk, start the seven-question match, or inspect one exact strategy version. Switch into the questionnaire as soon as the user asks what fits them or expresses a risk, capital, trading-mode, or holding-period preference; do not keep listing indefinitely or call a catalog item the best fit.

When the user already has an idea, summarize it, map only unambiguous preferences, and ask only the missing required questions. Public catalog search may help explain nearby strategies but never substitutes for formal matching. For non-English ideas, do not treat an empty default-English query as proof that no related strategy exists; use localized results or retrieve an unfiltered catalog and compare semantics. If none is related, turn the idea into a testable specification and explain that Research does not generate or execute arbitrary strategy code.

After the user chooses a catalog item, inspect its exact `slug@version`; never silently follow `latest`. On a fresh plugin without the launcher, inspect through the anonymous GET `/api/research/strategies/SLUG/VERSION` endpoint instead of installing the runtime. Cards from the anonymous Research recommendation endpoint are Research-visible at their response snapshot, but distribution changes or an emergency withdrawal can make an exact version unavailable later. If inspect or install reports that the exact version is no longer available, do not check the runtime, substitute another version, or choose another card: preserve the result, explain that the catalog changed, and offer to rerun the match or browse the anonymous Research catalog.

Only strategy ZIP downloads consume the anonymous source-network allowance: 20 per UTC day and 100 per UTC month, shared with Live downloads from the same IPv4 address or IPv6 `/64`. Search, inspect, versions, recommendations, runtime wheels, data downloads, and backtests do not consume it. Research still sends no login, token, cookie, machine ID, browser fingerprint, or local anonymous identifier. The service records the complete client IP and network quota key for approved ZIP downloads as disclosed in the Privacy notice; shared-NAT users share an allowance. An approved download and every retry count even if streaming is interrupted.

On `DOWNLOAD_QUOTA_EXCEEDED`, do not retry the download, install another version, replace local files, discard a formal recommendation, or describe the failure as a catalog change or integrity error. Preserve the three-card result and all local strategies, runs, catalog and runtime state. Explain in the current conversation language that the current source network's download quota is exhausted, and report the returned daily/monthly usage and UTC reset times without exposing an IP or network key. On `DOWNLOAD_QUOTA_UNAVAILABLE`, report a retryable service failure but do not automatically retry during the current install command. Keep minute burst `RATE_LIMITED` distinct from the daily/monthly download quota.

For an exact version confirmed visible in Research, offer factual comparison, details, or a historical backtest. Use `best_fit` and its returned preset by default only when the user has not selected another card. An unspecified request to "run" means historical backtesting, never Paper, Demo, or Live. Check or install the isolated runtime only after the user explicitly asks to backtest; opening the bundled local MCP Dashboard never installs it.

Keep all state under `~/.edgepilot-research/` on macOS/Linux or `%APPDATA%\EdgePilotResearch` on Windows. Never read `~/.edgepilot/`. If `EDGEPILOT_RESEARCH_HOME` is set, use that directory instead.

Host Python may run the bundled lightweight MCP/Dashboard and the bundled installer. It must not execute a backtest or import NautilusTrader. After installation, every runtime-dependent CLI command and any manually launched runtime Dashboard must use the generated launcher by absolute path; the installer does not add it to `PATH`. In this Skill, `edgepilot-research` always means that launcher:

- macOS/Linux: `~/.edgepilot-research/bin/edgepilot-research`
- Windows: `%APPDATA%\EdgePilotResearch\bin\edgepilot-research.cmd`

Do not start a runtime-dependent CLI command or a second manual Dashboard with host `python`/`python3`/`py`, `python -m edgepilot_research`, or a `PYTHONPATH` that points at the plugin `src/`. Those invocations skip the locked venv. The bundled MCP entry point is the sole exception: Codex starts it from `.mcp.json`, it remains lightweight, and it delegates a confirmed backtest to the active runtime Python.

Before a backtest command, install or check the isolated native runtime. Do not install it merely to launch the Dashboard. On the first backtest the Dashboard asks for explicit confirmation, shows the locked size and location, reports real download bytes and installation stages through existing job polling, and then automatically starts the requested backtest with the runtime Python. Marketplace catalog requests are independent of runtime installation and never send a runtime-lock header. Treat this as the plugin's first-use setup: own the complete check, disclosed consent, installation, verification, and requested operation instead of asking the user to find or run scripts. On the first runtime-dependent request in each newly installed or upgraded plugin version, run the bundled installer from this Skill's plugin root even when `runtime status` says an older release exists. The installer is content-addressed and idempotent: a matching release is only verified and reactivated, while a changed plugin digest or lock creates a new release. This prevents the stable launcher from silently continuing to use an older plugin copy.

On a fresh runtime installation, run the bundled installer with host Python first:

```bash
python3 skills/edgepilot-research/scripts/install_runtime.py
```

```bat
py -3 skills\edgepilot-research\scripts\install_runtime.py
```

Then verify with the launcher, not host Python:

```bash
~/.edgepilot-research/bin/edgepilot-research runtime status
```

```bat
%APPDATA%\EdgePilotResearch\bin\edgepilot-research.cmd runtime status
```

If the Windows `.cmd` exits with a syntax error, re-run the installer; an already-installed matching release still rewrites the launcher.

If reviewed wheel files are already available locally, pass their directory without changing the lock:

```bash
python3 skills/edgepilot-research/scripts/install_runtime.py --wheelhouse /path/to/wheels
```

The installer displays the exact platform, native-code notice, per-platform total, actual download bytes, download origins, cache hits, state directory, and live stages for cache/download processing, venv creation, locked installation, verification, and activation. Continue only after the user explicitly agrees. Host permission prompts remain separate and must not be bypassed. It follows the bundled lock exactly: the customized NautilusTrader wheel comes from EdgePilot, while locked public dependency wheels come directly from `files.pythonhosted.org`. Never add custom indexes, URLs, hashes, mirrors, dependencies, or a dynamic PyPI resolver. Never `pip install nautilus_trader` / `nautilus-trader` from PyPI, GitHub, or any other public index, on macOS, Windows, or Linux. The published runtime supports Apple Silicon Macs (`arm64`) and 64-bit Windows (`amd64`); Intel Macs and Linux are unsupported. Unsupported platforms fail before download; do not install system Python automatically.

When a true Intel Mac is detected, explain in the user's current language that this Mac uses an Intel processor, EdgePilot Research does not support Intel Macs, supported Macs use Apple Silicon (M-series), and no runtime files were downloaded or changed. If an Apple Silicon Mac is running an x86_64 process through Rosetta, explain that the machine is supported but the user must retry from a native arm64 Terminal and Python. Do not describe a Rosetta process as Intel hardware.

The customized NautilusTrader wheel uses the exact public R2 URL recorded in `runtime-lock.json`. Do not replace it with a PyPI wheel. The installer already sends a browser-like User-Agent. If a locked URL returns HTTP 403 with `error code: 1010`, retry the **same** URL with `curl` before using the local wheelhouse recovery path:

```bash
# macOS / Linux — save using the exact filename from runtime-lock.json
curl -L --fail -A "Mozilla/5.0" -o "$LOCKED_FILENAME" "$LOCKED_NAUTILUS_URL"
python3 skills/edgepilot-research/scripts/install_runtime.py --wheelhouse "$PWD"
```

```bat
curl.exe -L --fail -A "Mozilla/5.0" -o "%LOCKED_FILENAME%" "%LOCKED_NAUTILUS_URL%"
py -3 skills\edgepilot-research\scripts\install_runtime.py --wheelhouse %CD%
```

Catalog GETs that bypass the CLI should use the same `-A "Mozilla/5.0"` (or `curl.exe` on Windows).

After installation, use only the stable launcher under the Research state directory for CLI backtests and manually launched runtime commands. On Windows use `%APPDATA%\EdgePilotResearch\bin\edgepilot-research.cmd`. Do not run `edgepilot_research.cli` directly with the bootstrap/system Python. The already-running bundled MCP Dashboard remains valid because its backtest worker invokes that same active runtime Python. If the user requested only a CLI backtest, do not start another Dashboard.

In the command examples below, `edgepilot-research` means that resolved stable launcher, not an unrelated executable found earlier on `PATH`.

Use exact installed strategy versions:

```bash
edgepilot-research strategies list
edgepilot-research backtest STRATEGY_SLUG --version 1.0.0 --days 90
edgepilot-research runs list
edgepilot-research runs show RUN_ID
```

For online discovery, use only the anonymous Research catalog:

```bash
edgepilot-research marketplace search "momentum"
edgepilot-research marketplace versions STRATEGY_SLUG
edgepilot-research marketplace inspect STRATEGY_SLUG --version 1.0.0
edgepilot-research marketplace install STRATEGY_SLUG --version 1.0.0
```

Access the public Research catalog over HTTPS whenever current catalog data is needed. Prefer the CLI, but treat network failures as channel-specific: if terminal DNS is restricted, retry the same command with the environment's network permission or outside the sandbox; if the in-app browser returns `ERR_BLOCKED_BY_CLIENT`, use another available network-capable web/search tool or the permitted command-line request. For example, `curl -A "Mozilla/5.0"` (Windows: `curl.exe`) `https://edge-pilot.rivendell.capital/api/research/strategies` when the strategy list is required. Default Python `urllib` is rejected with 403/`1010`; do not treat that as a missing catalog or switch to PyPI. Do not ask the user to copy a public JSON response unless every available network-capable tool has failed. Do not use this fallback for authenticated endpoints, arbitrary third-party URLs, exchange adapters, or order execution.

When the plugin MCP is enabled, use `open_dashboard`; it returns the verified current loopback URL and no second process is needed. When onboarding opens the Dashboard, call `open_dashboard` with the same `locale` used for `recommend_strategies`; for another Dashboard request, pass the canonical current conversation locale when it is supported. The returned URL owns this per-open language choice; do not store it in shared Dashboard state. Outbound network access is required only when that Dashboard searches, recommends, inspects, or installs from the anonymous Marketplace. If the MCP is unavailable and the user explicitly asks for the manual runtime Dashboard, verify the anonymous catalog first and start the generated launcher with network permission:

```bash
~/.edgepilot-research/bin/edgepilot-research ui --host 127.0.0.1 --port 8686
```

```bat
%APPDATA%\EdgePilotResearch\bin\edgepilot-research.cmd ui --host 127.0.0.1 --port 8686
```

Do not start a second Dashboard with host Python or open a cached page of a stopped backend. For the manual launcher fallback, keep the process session alive and verify that `/api/health` matches `dashboard.json` before opening it. If its Marketplace preflight exits with `DNS_FAILED`, `CONNECT_TIMEOUT`, or `REMOTE_CONNECTION_FAILED`, obtain network permission and retry rather than bypassing it. The bundled MCP Dashboard starts without a runtime or Marketplace preflight so cards and the local page remain available during transient network failure; individual Marketplace calls must still report the real network error.

Never start the manual launcher while the bundled MCP Dashboard is available. To restart a manually launched Dashboard, use the stable launcher with `ui --stop`; it verifies the private instance record against health, obtains the local CSRF token, refuses queued/running backtests, and returns the exact host/port to reuse. Never call the endpoint with hand-built data or kill an arbitrary PID. A Dashboard started before this protocol is legacy: stop it through an owned host process handle only, otherwise ask the user to close it.

Downloaded Research packages are executable Python code. Only install first-party packages returned by the reviewed Research catalog. The runtime executes the formal `strategy.py` with NautilusTrader and the Manifest V2 benchmark preset; it never executes `research.py`.

Backtests accept only `--days 90` or `--days 365` (default 90). Before execution, Research reads the selected preset's venue, instrument, bar type and venue settings, then atomically fills that exact period from that venue's reviewed public market-data client. It never accepts an arbitrary data URL, reads credentials, initializes an execution client, or places orders. Automatic download supports the reviewed venues only — currently Binance Futures and OKX bar markets; return `PUBLIC_DATA_UNSUPPORTED` for any other venue or data type. A period on a venue that pages a hundred bars at a time can take several minutes to fill; report the progress the backtest emits rather than presenting it as stalled.

A preset binds exactly one exchange. When a strategy ships more than one, say which exchange each preset reaches, and do not describe a backtest result as reproducing the strategy card's published numbers: Research always runs the most recent selected period, not the benchmark window.

Users may still import a local CSV explicitly:

```bash
edgepilot-research data import --strategy STRATEGY_SLUG --version 1.0.0 --market 0 --csv bars.csv --instrument-json instrument.json
```

If automatic download fails, report the exact public-data error and retain the previous catalog. If imported catalog data is missing, return the exact import command.

Explain the dataset, period, parameters, fee assumption, annualized return, maximum drawdown, Sharpe ratio, trade count, and reproduction command. Historical performance does not predict future results and is not investment advice.

Never request login, account details, exchange credentials, API keys, secrets, passphrases, or permission to place orders. If the user asks to trade, explain that EdgePilot Research supports historical research only.

This Skill is a release candidate until the target public directory completes its own review. Do not tell users that runtime downloads, native installation, or local process execution are supported on a ChatGPT/Codex surface unless that exact surface has passed the release checklist. If local execution is unavailable, explain the limitation; do not silently switch to the Live product, PyPI, arbitrary code execution, or a remote trading service.
