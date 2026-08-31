# EdgePilot Research

Public, account-free strategy discovery and reproducible historical backtesting. This product does not connect trading accounts, accept exchange credentials, or place orders.

## Install with Codex

When you attach this extracted plugin directory to a Codex task, send the whole
request below. The second sentence must be part of your request because files
attached to a task provide context; they do not become user instructions by
themselves.

```text
Install this EdgePilot Research plugin. After installation, read the "Post-install guidance" section in README.md. If this Codex surface can create tasks, create and start the guided first-use task with its localized prompt; otherwise include that prompt in your final response.
```

## License

EdgePilot Research is proprietary software made publicly installable for personal and organizational internal research. It is not open-source software. Redistribution, republication, resale, sublicensing, and use to provide a competing hosted or managed service require prior written permission from EdgePilot. See [`LICENSE`](LICENSE); third-party components remain governed by [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and their respective licenses.

The public ZIP is a complete plugin transport archive, not a standalone Skill ZIP. Build both `edgepilot-research-openai-VERSION.zip` and `edgepilot-research-claude-VERSION.zip` together with `scripts/package_research.py --target all --package`. The command shares one fast remote HEAD/range verification and commits neither archive unless both pass. Both contain one Skill at `skills/edgepilot-research/SKILL.md`; the Claude build renders `${CLAUDE_PLUGIN_ROOT}` paths from that single source during packaging. Do not maintain or install a second copy of the Skill.

The plugin deliberately contains no third-party wheels. On a supported local-execution surface, run `skills/edgepilot-research/scripts/install_runtime.py`. It selects the immutable platform entry in `runtime-lock.json`, shows cache hits, matching local-wheelhouse files, and only the downloads still required before consent. `--wheelhouse /path/to/wheels` may supply any subset of locked files; every supplied file is still checked by exact filename, size, and SHA-256. The installer installs the complete locked wheelhouse without resolving dependencies at install time. The customized NautilusTrader wheel comes from EdgePilot; locked public dependency wheels come directly from `files.pythonhosted.org` and are not mirrored by EdgePilot. The host must already provide the CPython minor version named by that entry.

The bundled Codex stdio MCP completes its protocol startup without starting the loopback Dashboard. The first `open_dashboard` call starts or reconnects to the Dashboard without the native runtime and returns its real URL; the default port is attempted once and may fall back to an operating-system-assigned loopback port. Installation reports each cache/download file and the venv, install, verification, and activation stages. The first confirmed Dashboard backtest installs the content-addressed runtime in the existing job, displays real network-download bytes, and automatically continues the backtest with the active runtime Python. Manual CLI backtests use the stable state-directory launcher (`~/.edgepilot-research/bin/edgepilot-research` on macOS or `%APPDATA%\EdgePilotResearch\bin\edgepilot-research.cmd` on Windows).

The published Codex MCP always uses the production Research Marketplace origin and the standard Research state directory. It does not forward `EDGEPILOT_RESEARCH_ORIGIN` or `EDGEPILOT_RESEARCH_HOME`, and its launcher removes both variables before starting Python as a second isolation boundary. Repository development uses `scripts/local_debug.sh`, which explicitly supplies an isolated local state directory and local Server origin without changing published-plugin behavior.

Before replacing plugin files, the installer runs the candidate package's lightweight `skills/edgepilot-research/scripts/stop_local_dashboard.py --stop-if-running`. It does not require the native runtime: it reports `not_running` for a fresh install, or stops only the bundled Dashboard whose private record, health nonce and authenticated stop handshake agree. An unverifiable or incompatible service stops in-place activation instead of triggering a PID- or process-name-based kill; Codex restart remains the fallback.

Runtime, strategies, catalog data and runs are isolated under `~/.edgepilot-research/` (or `%APPDATA%\EdgePilotResearch` on Windows). The installer writes `bin/edgepilot-research` and, on Windows, `bin/edgepilot-research.cmd`. After installation, run that launcher by absolute path for every command, including `runtime status`, `backtest`, and `ui`. Do not invoke the plugin with host Python or `python -m edgepilot_research`; that skips the locked venv, so the Dashboard can report a local runtime while backtests fail with `edgepilot-core is unavailable`. `runtime repair` validates state and rewrites the launcher; `runtime uninstall --yes` removes only runtime files and preserves strategies, catalog and runs.

The first release lock supports macOS arm64 with CPython 3.12 (206,943,606 bytes across 15 wheels) and Windows amd64 with CPython 3.12 (159,195,940 bytes across 15 wheels). Intel Macs are not supported. Linux is not in the first release: the existing CPython 3.14 Nautilus wheel cannot currently form a binary-only dependency closure because a compatible `msgspec>=0.21.1` wheel is unavailable. Unsupported platforms fail with supported-hardware guidance before downloading or changing runtime state. An Apple Silicon Mac running through Rosetta is identified separately and told to retry from a native arm64 process.

Backtests execute the installed package's formal `strategy.py` through NautilusTrader using any preset shipped in the package. The CLI and Dashboard allow 90-day or 365-day periods, defaulting to 90. Before execution, Research uses the preset's exact venue, instrument and bar type to download public bars into an atomically replaced local catalog; it does not read credentials or initialize an execution client. Reviewed venues are listed in [`DATA_SOURCES.md`](DATA_SOURCES.md) — currently Binance Futures and OKX — and any other venue or non-bar data type fails explicitly with `PUBLIC_DATA_UNSUPPORTED`. The selected period is canonical `[start, end)` close time, so the bar closing at `start` is retained and the bar closing at `end` is excluded; each venue's native stamping is normalised to that close time, which for OKX means shifting its opening stamps forward by one interval. A venue that pages a hundred bars at a time can take minutes to fill a long period, so download progress is reported to the Dashboard while it runs. When the process has standard `HTTPS_PROXY` or `https_proxy` set, Research forwards that value to the native HTTP client for the current request; it does not persist the proxy or ship a default address. CSV data import remains available for a local file and explicit Nautilus instrument JSON, and arbitrary data URLs are never accepted.

A preset binds exactly one exchange, because `strategy.instrument_id` carries a venue suffix. The strategy workspace therefore labels each preset with the exchange it reaches, and states that a backtest always covers the most recent selected period rather than the benchmark window shown on the strategy card.

Online catalog access is anonymous and limited to `/api/research/**`. Catalog search, inspection, formal three-card recommendations and package download do not require an account, login, token, cookie, machine ID, browser fingerprint, or installed runtime, and do not send runtime-lock metadata to the Marketplace service. The local MCP recommendation tool submits only the V2 seven-answer questionnaire and locale, and the service does not persist questionnaire answers. Results are research artifacts, not investment advice.

The Dashboard catalog can filter by an exact logic-compatible exchange and displays those exchange codes on strategy cards. This label uses the published `strategy_logic_only` assessment: it does not claim that the local runtime can download that venue's public data, that the referenced instrument exists there, or that backtesting or live execution has been verified. Research backtests continue to enforce their separate public-data and runtime capabilities.

Only strategy ZIP downloads consume the shared source-network quota: 20 per UTC day and 100 per UTC month. Search, inspection, version lists, recommendations, runtime wheels, public market data, and backtests do not consume it. IPv4 is limited by the complete address and IPv6 by its normalized `/64`; users behind a shared NAT therefore share the same allowance. An approved download counts even if streaming is interrupted, and a retry counts again. When the allowance is exhausted the CLI and Dashboard stop without modifying the installed strategy, catalog, runtime, or saved runs, show `DOWNLOAD_QUOTA_EXCEEDED`, the daily/monthly usage, and UTC reset times, and do not retry automatically.

Although Research does not identify a user account, the Marketplace records the complete client IP and its network quota key for each approved strategy ZIP download. Approved download records are retained for 180 days, with backups retained for at most 30 additional days. Rejected requests are not added to download records; their IPv4 address or IPv6 `/64` network key may appear in restricted application logs retained for at most 14 days. See the linked Privacy notice for the governing disclosure.

After installation, the ChatGPT plugin exposes `Help me choose a strategy` and `Show me the available strategies` as its two starting prompts. On the first reply, the Skill introduces EdgePilot Research, explains the local Dashboard lifecycle, and continues in the user's conversation language. Formal matching uses the bundled `recommend_strategies` MCP tool so ChatGPT can render the three recommendation cards; the tool calls the anonymous `/api/research/recommendations` endpoint and remains scoped to Research/all exact versions. If that tool is unavailable, the Skill preserves the answers and offers anonymous catalog browsing; it never installs the runtime merely to obtain a recommendation, copies the ranking algorithm, requires login, or falls back to Live.

## Post-install guidance

After installation, reply in the user's current conversation language. When the
current Codex surface exposes a task-creation tool, the installation request above
is explicit authorization to create and start a fresh task, using the same project
when applicable, with the localized prompt below as its initial message. Open that
task for the user when the host supports navigation. Do not use task handoff: it
moves an existing task and does not create the fresh MCP/tool context required after
installation. If task creation is unavailable, tell the user to create a new Codex
task and include the prompt for one-click copying. No restart is needed when the
verified Dashboard preflight reports `not_running` or `stopped` and
`verify_activation` reports `activation: ready`. Restart Codex only when a verified
old Dashboard remains, the new task does not expose the installed MCP, or activation
reports a version mismatch. Translate the following prompt naturally while
preserving the exact `@EdgePilot Research` mention and its request to open the
Research Dashboard immediately, then ask about preferences one question at a time,
obtain confirmation, and show three recommendation cards:

```text
@EdgePilot Research Open the Research Dashboard immediately, then help me choose a research strategy. Ask about my preferences one question at a time and show three strategy recommendation cards after I confirm them.
```

After activation succeeds, the new task calls `open_dashboard` immediately, presents the verified local link or opening result, and asks the first preference question in the same reply. It then preserves the existing one-question-at-a-time flow and renders three recommendation cards after confirmation. The user does not need to send another Dashboard command. If the host blocks automatic navigation, the tool result still provides the verified clickable URL. This flow does not install or check the native runtime.

The Dashboard Marketplace includes **Find the right strategy**. Its independent page collects seven canonical answers plus one optional in-memory note, displays the complete three-result response, and can install or update the chosen exact version before opening its benchmark preset workspace. It does not automatically install the runtime, download data, or start a backtest. A catalog change between recommendation and installation is reported explicitly; the Dashboard never substitutes another result or version.

The local Dashboard is built from the Git-tracked `ui/` source and distributed as production assets under `src/edgepilot_research/ui_assets/app/`. Local `npm run build` output at that path is ignored and must not be committed. Formal packaging installs dependencies from `package-lock.json`, builds the bundle once in a temporary directory, and injects the same bytes into both target archives; it rejects a missing HTML shell, missing or unhashed JavaScript/CSS references, external script/style references, and source maps.

The bundled MCP Dashboard can start without Marketplace connectivity, so local history and the website remain available during a network outage. Search, recommendations, inspection and installation still require anonymous outbound HTTPS and report their own network failure. A manually started runtime Dashboard keeps its existing Marketplace preflight behavior; browser choice does not grant network access to the local Python backend.

A current Dashboard can be restarted safely with the stable launcher's `ui --stop` command, which requires its private instance record and `/api/health` identity to agree. The underlying loopback stop endpoint accepts no PID and refuses to stop while a backtest is queued or running. Dashboards from older plugin versions do not have this identity protocol and must be closed through an already-owned host process handle or by the user before restart.

## Release status

The runtime-download design is implemented in this repository, but public-directory acceptance is an external release gate. Packaging success does not mean that ChatGPT or Codex has approved local process execution, native wheel installation, runtime downloads, or every target surface. Before publishing, complete the checklist in [`../docs/research-v2-release.md`](../docs/research-v2-release.md), including native tests, license/SBOM review, HTTPS hosting, directory security scans, and end-to-end tests on every advertised surface. Unsupported surfaces must not be advertised.

- Privacy: https://edge-pilot.rivendell.capital/privacy
- Terms: https://edge-pilot.rivendell.capital/terms
- Support: https://edge-pilot.rivendell.capital/support
- Support email: agent_strategy@rivendell.capital
- Research OpenAPI: https://edge-pilot.rivendell.capital/openapi/research.json
