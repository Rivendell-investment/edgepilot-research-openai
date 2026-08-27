# EdgePilotAI Research FAQ — OpenAI and Codex

## What is EdgePilotAI Research?

EdgePilotAI Research supports strategy discovery, configuration, public-data historical backtests, and reporting inside supported AI workspaces.

## Is Research a trading bot?

No. Research does not connect trading accounts, accept exchange credentials, or place orders.

## Do I need an EdgePilotAI login or trading account?

No. Supported Research workflows are account-free and do not require exchange credentials.

## Do I need to write code?

No code is required to begin. You can describe the market, strategy idea, or risk preferences in plain language. EdgePilotAI can ask for missing constraints and show relevant strategies for review.

## How do I begin after installing it?

Create a new task in the supported OpenAI or Codex workspace and try `Help me choose a strategy` or `Show me the available strategies`.

## Why am I asked for permission before the first backtest?

The first backtest may need to prepare or install a local runtime. EdgePilotAI asks for explicit consent before this local operation.

## Which desktop systems does the first public runtime support?

The published installation guide lists Apple Silicon macOS and 64-bit Windows with CPython 3.12. Intel Macs and Linux are not supported by the first public runtime. Availability may also depend on the AI host, account, region, and release channel.

## What historical periods are available?

The published workflow supports 90-day and 365-day periods, with 90 days as the default.

## What should I inspect in a backtest?

Review the dates and data, maximum drawdown, fees, slippage and funding assumptions, trade count, parameters, robustness, and the strategy and runtime versions. Return alone is not enough.

## Does a backtest guarantee future returns?

No. Historical and simulated results depend on their data and assumptions. They are research evidence, not a prediction or promise.

## Where is the Claude version?

Use the official [EdgePilotAI Research for Claude repository](https://github.com/Rivendell-investment/edgepilot-research-claude).

## Official sources

- [Research overview](https://www.edgepilotai.io/en/research/)
- [Installation guide](https://www.edgepilotai.io/en/how-to-use/)
- [Machine-readable installation guide](https://www.edgepilotai.io/install/edgepilot-install.md)

If product scope or runtime support changes, the official website is the source of truth.
