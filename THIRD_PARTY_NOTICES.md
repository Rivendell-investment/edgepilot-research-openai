# Third-party notices

The lightweight plugin archive contains EdgePilot Research source and the shared
`edgepilot_backtest_core` source; it contains no third-party wheels. The installer
uses the Python standard library, but the installed native runtime is a separate
artifact and includes NautilusTrader and every dependency named in the immutable
`runtime-lock.json`. The customized NautilusTrader wheel is downloaded from
EdgePilot; locked public dependency wheels are downloaded from
`files.pythonhosted.org` without an EdgePilot mirror or install-time dependency
resolution.

NautilusTrader is licensed under LGPL-3.0-or-later. For a modified build, the
release must publish the corresponding source, build instructions and change
notice for the exact wheel version through a durable HTTPS location. See
`vendor/MODIFICATIONS.md` for the repository's change record. This notice is not
a substitute for the complete license bundle required by the release checklist.

The release archive includes platform SPDX SBOMs, a third-party inventory,
upstream license and notice texts, and the modified NautilusTrader source offer
under `licenses/`. Packaging verifies that these materials cover every wheel in
every platform entry of the runtime lock. An incomplete inventory blocks the
build.

Downloaded strategy packages are executable Python code and may carry their own
license and notices. Only first-party, Git-provenance-verified packages approved
for the selected runtime lock are supported. User-provided datasets remain under
their original terms.
