# E30 CAN Dash Agent Notes

## Project Summary

This project is a custom digital dashboard for a BMW E30.

The display is meant to feel period-correct:
- The default screen should evoke the old-school E30 clock look and feel.
- Additional screens should present live engine and vehicle data in a clean, readable way.
- The overall experience should feel like an OEM-plus upgrade, not a generic modern tablet UI.

The current app reads CAN data from a Link ECU, decodes it with the bundled DBC file, and renders a fullscreen `pygame` interface intended for an embedded display.

## Primary Goals

- Preserve the vintage E30 aesthetic.
- Make critical engine data easy to read at a glance while driving.
- Keep touch interactions simple and reliable.
- Favor robustness on embedded hardware over abstraction for its own sake.

## Product Direction

When making UI or UX changes:
- Keep the clock-inspired landing page as a core part of the experience.
- Use restrained colors and strong contrast.
- Prefer layouts that resemble gauges, clocks, warning indicators, and simple automotive instrumentation.
- Avoid overly glossy, futuristic, or phone-app-like design patterns.
- Any new engine data view should feel consistent with analog cluster design language.

## Technical Context

- Main runtime: `app.py`
- CAN schema: `dbc/Link_Generic_Dash.dbc`
- Video smoke test: `test_video.py`
- Rendering stack: `pygame`
- CAN stack: `python-can`, `cantools`
- Target environment: embedded Linux / Raspberry Pi style hardware with a connected display and CAN interface

## Structure Notes

`app.py` currently contains:
- runtime configuration
- live shared data state
- CAN reader thread
- rendering helpers
- page drawing functions
- main event loop and touch handling

This is acceptable for a prototype, but if the app grows, prefer splitting along these boundaries:
- `config`
- `can_io`
- `signals` or `telemetry`
- `ui/pages`
- `ui/widgets`

## Guardrails For Future Changes

- Do not remove the vintage clock concept from the product.
- Do not redesign the UI into a generic modern dashboard without a clear request.
- Keep performance predictable; this app should remain lightweight.
- Be careful with hardcoded hardware assumptions and absolute device paths.
- Treat DBC signal names as a contract and verify them before adding new fields.
- Prefer graceful degradation when CAN data is missing.

## What Good Changes Look Like

- Better readability in sunlight or at a glance
- Cleaner mapping between decoded ECU signals and displayed values
- Safer configuration for deployment on different hardware
- More maintainable separation between CAN input and rendering
- UI improvements that still look at home in an E30 interior
