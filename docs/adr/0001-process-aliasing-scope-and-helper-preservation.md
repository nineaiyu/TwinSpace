# Process Aliasing Scope and Helper Preservation

Status: accepted

## Context
PR #31 introduced physical Mach-O binary renaming during hard cloning to allow proxy clients like Clash and Surge to distinguish clone processes by `PROCESS-NAME`. However, the recursive renaming logic swept through the entire `.app` bundle, modifying auxiliary helper binaries (`QQ Helper.app`, `QQ Helper (Renderer).app`) and nested sub-applications (`QQEXGuild.app`). In Chromium and Electron multi-process architectures, helper binaries must retain their exact original bundle names and `CFBundleExecutable` identifiers; renaming them breaks internal helper path resolution (`helpers_path.mm`), disrupts Mojo IPC protocol registrations (`--standard-schemes`), and causes infinite deserialization crash loops before window presentation.

## Decision
We restrict process aliasing for all Chromium and Electron applications:
1. **Main Process Aliasing Only**: Only the root Main Executable (`Contents/MacOS/<CFBundleExecutable>`) and its corresponding C launcher surrogate are renamed to the clone name.
2. **Helper and Sub-App Preservation**: All auxiliary Helper Bundles (`*Helper*.app`), embedded Frameworks, Resources, PlugIns, and Nested Sub-Apps must remain 100% untampered on disk.
3. **Multi-layer Runtime Detection**: Chromium/Electron architectures are detected through recipe metadata (`app_type`), notable frameworks (`Electron Framework`, `QQNT`, `Chromium Embedded Framework`), asar archives (`app.asar`, `electron.asar`), and helper bundle patterns in both `AppProber` and `HardCloneEngine`.

## Consequences
- **Positive**: Eliminates Mojo IPC crashes and infinite validation error loops across all Electron and Chromium clones (QQ, Claude, Discord, Slack, VS Code, Bilibili, Arc, Edge, Chrome).
- **Positive**: Nested sub-applications (like QQ Guild, Mini Programs, and Documents) run without secondary process initialization failures.
- **Trade-off**: In proxy routing rules, outbound connections spawned directly by isolated helpers (if any) will report the original helper binary name rather than the clone name. However, all primary traffic initiated or orchestrated by the main application process matches the clone name as expected.
