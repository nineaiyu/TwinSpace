English | [简体中文](ReleaseNote_zh.md)

# TwinSpace Release Notes

## [v1.6.1] - 2026-10-29

### 🩹 Fixes
- **Batch stop reported "still running" under the wrong title**: the failure dialog reused the "Environment Creation Failed" heading even though nothing was being created. Stop failures now say "Could Not Stop the Apps" and list the apps that are still running, with a hint to retry or quit them from Activity Monitor; the create flow keeps its own title.
- **Stopping Electron clones did nothing**: WorkBuddy / Qoder / Trae install a SIGTERM handler and kept running, so after four seconds they were reported as "still running". Stopping now escalates `SIGTERM → wait 4s → SIGKILL → wait 2s` (data lives outside the bundle, so only unsaved window state is lost).
- The generic error title no longer claims "Environment Creation Failed" for updates, backups and deletions.

## [v1.6.0] - 2026-10-29

### 🌍 International WorkBuddy AI / CodeBuddy AI
- **Two new international builds**: the environment wizard now offers **WorkBuddy AI** (`com.workbuddy.workbuddy-ai`) and **CodeBuddy AI** (`com.tencent.codebuddy`) alongside the CN builds (`com.tencent.workbuddy.mac` / `com.tencent.codebuddycn`), fully independent of each other.
- **Opt-in by default**: the international builds are only included when ticked manually, so existing environments and the CLI default app list are unchanged.
- **AI-suffixed clone names**: ticking them generates `WorkBuddyAI-<env>` / `CodeBuddyAI-<env>`, which can coexist with the CN `WorkBuddy-<env>` / `CodeBuddy-<env>` in the same environment.
- **Isolation recipes included**: `com.workbuddy.workbuddy-ai.yaml` (the `workbuddy-ai` deep link) and `com.tencent.codebuddy.yaml` (the `codebuddy` deep link) keep login callbacks inside their own clone instead of waking the host app.
- The clone-name field unlocks as soon as an international build is ticked, and keeps following the environment name while it stays off.

## [v1.5.3] - 2026-10-29

### 🩹 Fixes
- **The "running" badge disappeared a second after launching an app**: for clones started through a launcher (or Electron apps with nested helper bundles), NSWorkspace reports the executable path (`…/ZCode-b1.app/Contents/MacOS/ZCode-b1`) or an inner helper bundle, while clones are indexed by their `.app` path — the lookup failed and the green dot was cleared. Running paths are now folded back to the outermost `.app`, and clones that are believed to be running but missing from the snapshot are re-checked once against the process table.

## [v1.5.2] - 2026-10-28

### 🩹 Fixes
- **Updates failed where a "safe delete" hook is installed**: some launchers prepend a wrapper directory (a sandbox safe-delete shim) to PATH, so the `rm -rf` inside the clone/update script was rejected with `SAFE_DELETE_BULK_CONFIRM_REQUIRED` and large app bundles (thousands of files) could not be updated. Clone scripts now run with `/usr/bin`, `/bin`, `/usr/sbin` and `/sbin` first on PATH so `rm`, `cp` and friends resolve to the system binaries.

## [v1.5.1] - 2026-10-28

### 🩹 Fixes
- **Update / rebuild confirmation flashed and vanished**: the second confirmation used an application-modal session, which ended immediately and closed the alert before the Update / Cancel buttons could be used. It is now presented as a sheet on the main window and waits for the user's choice.

## [v1.5.0] - 2026-10-28

### 🖱 Batch Actions, Rubber-Band Selection & Update Badges
- **Rubber-band selection (My Environments / clone cards)**: press and drag a translucent box over icons or blank space and everything it touches is selected; auto-scrolls at the page edges, `Cmd + A` selects all, `Esc` clears (pressing `Esc` mid-drag cancels that sweep and restores the previous selection), a plain click on blank space clears the selection, and `Shift`-dragging appends.
- **Right-click batch menu**: with several items selected, right-clicking any selected one offers Open / Quit / Update / Rebuild from Source for the whole selection — no need to switch to the table; right-clicking blank space offers Select All / Clear Selection. The batch bars above the environment page and the clone card grid are gone.
- **Clone table batch actions**: the toolbar becomes "Open (N) / Close (N) / Update (N) / Delete (N)" as soon as several rows are selected.
- **⬆ update badges**: the source app's `Info.plist` version is compared against each clone — the table gains a Version column showing `old → new`, clone cards show "update available", environment tiles show `⬆ <new version>` and the environment header shows "N to update". Badges are recomputed when the app becomes active again (e.g. after updating the source app in Finder).
- **Clearer update semantics**: "Update All" now only processes apps that are behind their source app, and a new "Rebuild All" keeps the old full-rebuild behaviour. Both skip running apps and list the app names (plus a "skipped (still running)" line) in a confirmation whose button reads Update / Rebuild / Cancel.
- **Progress feedback**: updates and rebuilds are mutually exclusive, and the environment card status line shows `Updating 2/3 · ZCode` while it works (and the failing app afterwards).

## [v1.4.0] - 2026-10-28

### 🕘 Last Opened Timestamps
- **Clones and environment apps now show when they were last opened**: a caption under the app icon reads "Opened today at 5:30 / Opened yesterday at 6:20 / Opened 2 days ago / Opened 5 days ago", and the same information appears on clone cards and in the table view.
- **Timestamps are persisted**: stored as `last_opened_at` in `clones.yaml`, so they survive restarts; a click and the matching system launch notification are deduplicated within 5 seconds.
- **Every launch path is covered**: besides the in-app launch buttons, TwinSpace listens to NSWorkspace launch notifications, so clones started from Finder or the Dock update as well.
- **New "Last Opened" column in All Clones**: appended to the table with header sorting; rows refresh in place after a launch without reloading the page.
- **WorkBuddy login deep-link fix**: the login page opens `workbuddy://` targets and could wake the host app; the scheme is now kept and pinned to the current clone.

## [v1.3.0] - 2026-10-26

### 🖥️ UI Rebuild & Native Interaction Fixes
- **Environments page is now an app icon grid**: 56pt real app icons with captions and run state, double-click to open, right-click menu (Open/Close, Edit, Rebuild from source, Reveal in Finder), single-click focus pill, and 2–6 adaptive columns.
- **Clone list upgraded**: real app icons in the name column (22pt), a new Environment column with filtering, 44pt full-width rows without zebra stripes, and SF Symbol icons on the bottom action bar.
- **One visual language**: full-size content window with a transparent titlebar, native sidebar material with an accent-tinted selection pill, 24pt titles and a 28pt search field; cards share 14/16pt corners and a soft shadow in both appearances.
- **Grouped-form pass**: settings, probe and doctor pages now use the same form card (13pt group title, 120pt label column, hairline separators, naturally sized buttons).
- **Fixed dead right-click menu items and double-click**: the native menu and gesture actions were wired with `invoke_` / `handleDoubleClick_` (missing colon), so AppKit could not find the receiver and silently dropped the action — the menu opened but items did nothing, and double-click never fired. They now use `invoke:` / `handleDoubleClick:`, and click/double-click/hover/menu handlers are installed on every view of a tile (Toga lays tiles out flat, so the icon and caption are siblings rather than subviews).
- **Configurable table icon column**: Toga's hardcoded 16pt cell icon width is overridden.
- **Deterministic device identity**: environment identity is derived from a stable scope hash, previewable without rebuilding a clone; environment cards show the UUID prefix and hostname, plus a device identity window.

## [v1.2.2] - 2026-10-26

### 🛠️ Stability Fix
- **Fixed the sporadic crash when launching a clone from an environment**: Toga tears down Auto Layout constraints from Python finalizers, so a garbage collection running on a worker thread (the subprocess call that opens a clone is a typical trigger) touched AppKit off the main thread, tripped an Auto Layout assertion and aborted TwinSpace with `SIGABRT` while the launched app kept running. Constraint removal and window toolbar cleanup are now queued and replayed on the main thread.
- Added regression tests covering immediate main-thread teardown and deferred background-thread teardown.

## [v1.2.1] - 2026-10-26

### 🧬 Per-Environment Device Identity & Per-App Control
- **Environment-scoped hardware identity**: every environment gets its own `IOPlatformUUID`, platform serial, disk media/volume UUID and device GUID, per-interface MAC addresses and hostname. Apps inside one environment share the same identity; different environments stay isolated.
- **Four read paths covered**: IOKit, DiskArbitration, `getifaddrs` and `gethostname`, so apps no longer treat multiple environments on one machine as the same device.
- **Enabled by default** for ZCode, WorkBuddy, CodeBuddy CN, Qoder CN and Trae CN; custom recipes can opt in via the `TWINSPACE_DEVICE_*` variables.
- **Per-app control on environment cards**: each app row has its own Open / Close button without affecting the rest of the environment; Open All is still available.
- **Docs**: hardware-identity isolation and the list of system-level values that cannot be isolated.

## [v1.2.0] - 2026-10-25

### 🌐 External Browsers, GUI/CLI Parity & New Icon
- **Fixed browser binding**: links and OAuth from environment apps now reliably open the environment's own browser — previously they silently fell through to the system default.
- **External browser support**: bind an environment to any browser without cloning it — `twinspace env create --browser "/Applications/Microsoft Edge.app"` keeps an isolated profile inside the environment; `--set-env APP=KEY=VALUE` covers per-app overrides.
- **GUI reaches CLI parity for environments**: a browser-binding selector (environment Chrome / system default / external browser with file picker) in the create window, plus Export Template, Restore Backup and Import Template on the environments page.
- **Host usage of environment browsers**: the env Chrome clone works standalone — launch it directly or set it as the macOS default browser; the choice survives `env update`.
- **New application icon** (blue tile with original + ghost app windows) shipped across the app, installer and documentation site.
- **Documentation overhaul**: accurate 39-recipe table, new Security & Privacy section, `TWINSPACE_*` environment-variable reference, and bilingual guide chapters for environments, external browsers and host-side usage.

## [v1.1.0] - 2026-10-25

### 🖱️ Interaction & Layout Overhaul
- Double-clicking a clone in the table now launches it; editing stays on the explicit toolbar button.
- Destructive delete buttons are red-tinted and right-aligned across the table action bar, clone cards and environment cards.
- The list/card view switch is now a visible segmented toggle, and the card grid adapts its column count (1–3) to the window width.
- First-run users (no clones, no environments) now land on the Environments page, and the clones empty state offers one-click guidance to create the first isolated environment.
- Search input is debounced so the list is not rebuilt on every keystroke; the main window enforces a 980×640 minimum size.
- The app now follows system Dark Mode changes on view switches instead of requiring a restart.
- Update installation shuts down through the normal exit path so the tray icon and log listeners are cleaned up.
- Filter and sort dropdown labels shortened for both languages.

## [v1.0.1] - 2026-10-25

### 🔒 Security & Reliability Hardening
- Fixed shell-quoting collisions in generated clone scripts: embedded Mach-O patch helpers now receive target paths via environment variables, so app paths containing spaces no longer silently skip patches, and special characters can no longer break out of the generated commands.
- Untrusted `CFBundleExecutable` metadata is now validated and escaped before it reaches generated C launchers and printf format strings.
- Admin-elevated scripts always run from a secure temporary file instead of being inlined into an AppleScript string.
- Proxy passwords are now fed to the macOS Keychain via stdin (`security -i`) instead of command-line arguments, keeping secrets out of the process list.

### 🐛 Bug Fixes
- Clone records with unknown fields are preserved (with a warning) instead of being silently dropped from `clones.yaml`.
- Logs view title now shows the line count again; the "environment already exists" hint no longer renders its raw key name.
- Automatic updates no longer silently fall back to an arm64 package on Intel Macs, and prerelease versions (e.g. `1.2.0-rc1`) compare correctly.
- Hard clones now honor legacy `ATB_*` recipe keys for isolation detection, sandbox entitlement extraction works on older macOS, and the sandbox entitlement check no longer misreports when a neighboring entitlement is `true`.
- `twinspace migrate` respects `TWINSPACE_HOME` / configured base directory; the release workflow now publishes `latest.json` so in-app update checks work.

### ✨ Improvements
- `twinspace env` commands are fully localized in Simplified Chinese and English.
- The CLI probes the system language once per invocation instead of on every message.
- Removed 28 dead translation keys, legacy `ATBTable`/`atb` naming, dead statements in the clone engine, and hardened `doctor` checks to use argument lists.

## [v1.0.0] - 2026-10-24

### 🎉 First Standalone Open-Source Release
- First release published from the standalone TwinSpace repository, shipping the rebranded `twinspace` package, CLI and macOS GUI.
- Streamlined language support to Simplified Chinese and English across the UI, CLI, online documentation and release notes.
- Rebuilt the bilingual online user guide (English / 简体中文) with automatic browser language detection.
- Added GitHub Actions automation: a CI test workflow and a tag-driven release workflow that publishes the arm64 GUI `.dmg` and the standalone CLI archive.

## [v3.0.0] - 2026-10-24

### 🚀 TwinSpace Rebrand & Isolated Environments
- Renamed the project from ATBClone to TwinSpace, with a new `twinspace` CLI and the default data root `~/TwinSpace`.
- Added one-click multi-app environments where Chrome, ZCode, WorkBuddy, CodeBuddy, Qoder and Trae share one isolated Chrome profile and data root.
- Added per-app custom clone names with validation and duplicate detection.
- Fixed Dark Mode multiline text rendering so log surfaces follow the active theme.

- Added CLI environment commands, portable YAML templates, batch updates and data backup/restore, plus legacy data migration.
## [v2.3.0] - 2026-09-23

### 🔄 Sidebar Update Error Formatting & Zero-Shift Layout
- **Prevented Vertical Layout Jitter**:
  - Completely revamped the sidebar update feedback mechanism to eliminate jarring vertical layout shifts caused by long, multiline error strings when network or update checks fail.
  - Replaced wrapping labels with fixed-height, native Cocoa single-line labels configured with `NSLineBreakByTruncatingTail` to guarantee immutable sidebar dimensions.
  - Introduced an intelligent error parser (`format_update_error`) that maps complex network and HTTP exceptions into concise, localized single-line statuses (e.g., Timeout, Network Error, HTTP status codes).
  - Added an automated 5-second timer to smoothly dismiss transient error messages and restore the sidebar to a clean resting state.

### 🌐 Comprehensive Multilingual Error Messages
- **Localized Update Feedback**:
  - Added 4 dedicated update error keys across all 9 supported languages (`update_error_short`, `update_error_timeout`, `update_error_network`, `update_error_http`).

### 🧪 Test Suite Expansion & Quality Assurance
- **Expanded Coverage**:
  - Added comprehensive test suites covering update error parsing, Cocoa truncation, and auto-dismissal (`test_sidebar_update.py`, `test_i18n_update_keys.py`).
  - Automated test suite expanded to **659 tests** with a 100% pass rate.

---

## [v2.2.1] - 2026-09-23

### 🛡️ Electron & Chromium Helper Preservation & Mojo IPC Stability
- **Resolved Child Process Crash Loops in Hard Clones**:
  - Fixed a critical issue where aggressive binary renaming in hard clones altered helper apps and nested sub-apps, breaking Chromium Mojo IPC and Mach port communications in apps like QQ/QQNT, VS Code, and Slack.
  - Strictly scoped process renaming for Chromium/Electron architectures: only the root executable (`CFBundleExecutable`) and the entry launcher are aliased.
  - All helper bundles (`*Helper*.app`), internal plugins, and nested sub-applications (e.g. `QQEXGuild.app`) in `Frameworks`, `Resources`, and `PlugIns` remain completely untampered.

### 🔍 Multi-Layer Electron & Chromium Architecture Detection
- **Enhanced App Probing & Fingerprinting**:
  - Upgraded `AppProber.detect_app_type` to recognize `QQNT.framework`, asar package variants (`app.asar`, `electron.asar`, `application.asar`), and helper bundle patterns.
  - Introduced dual-check runtime verification in `HardCloneEngine` via explicit flags and filesystem inspection to prevent misclassification.

### 📐 Architecture Documentation & Decision Records
- **Formalized System Invariants**:
  - Added root `CONTEXT.md` and ADR `0001-process-aliasing-scope-and-helper-preservation.md` documenting process aliasing boundaries and IPC preservation rules.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Added specialized unit tests for helper preservation and QQNT/asar detection (`test_process_names.py`, `test_app_prober.py`).
  - Automated test suite expanded to **649 tests** with a 100% pass rate.

---

## [v2.2.0] - 2026-09-22

### 📝 Clone Notes & Instant Search Filtering
- **Personalized Clone Annotations**:
  - Added a dedicated `notes` field in `CloneRecord` and `CloneEditWindow`, allowing users to record custom context (e.g. account credentials hint, purpose, region, or profile tag).
  - Added a new 'Notes' column in the `CloneListView` table view with support for header click sorting (ascending/descending).
  - Integrated fuzzy search matching on notes text in the top toolbar search bar for rapid filtering across large clone libraries.
  - Non-empty notes are neatly displayed on `CloneCard` with text truncation.
  - Complete 9-language localization for notes labels and input placeholders.

### 📐 Ergonomic Window & Sidebar Layout
- **Enhanced Desktop Visibility**:
  - Expanded default main window dimensions to `1300 x 760` (from 1200 x 680), providing optimal breathing room for wide tables and grid cards.
  - Widened the left navigation sidebar to `240px` (from 200px), enhancing readability for navigation items, badges, and the update checker.

### 🔬 Clang Compilation Verification for Dynamic Libraries
- **Compiler-Level Hook Resilience**:
  - Added automated integration tests invoking real `clang` compiler runs for all injected dynamic libraries:
    - Cocoa / POSIX interpose hook dylibs (`libatbclone_hook`).
    - Custom Lark/Feishu and ChatGPT process isolation dylibs.
    - Environment variable injection dylibs (`libatbclone_env`).
  - Guarantees seamless compilation without warnings or syntax regressions across macOS developer toolchains.

### 🧪 Test Suite Expansion & Display-Independent Assertions
- **Robust Continuous Testing**:
  - Decoupled GUI integration tests from display-dependent window dimensions, ensuring deterministic test execution across headless and diverse multi-monitor environments.
  - Automated test suite expanded to **648 tests** with a 100% pass rate.

---

## [v2.1.1] - 2026-09-18

### 🔧 C Launcher Variable Scope Fix & Compilation Resilience
- **Resolved Launcher Compilation Error in Hooked Applications**:
  - Fixed a C compilation failure caused by variable scope shadowing (`dir` redefinition) in generated C launchers for applications with custom dynamic library hooks (such as Lark/Feishu and ChatGPT).
  - Enclosed `hook_block` logic in an isolated compound scope block `{ ... }` within the C launcher generator, preventing variable name collisions.
  - Added real `clang` compilation tests for Lark and ChatGPT launcher templates to guarantee ongoing compiler compatibility.

### 🛡️ Process Name Rewriting Hardening & Non-Standard Bundle Resilience
- **Robust Exception Handling**:
  - Hardened executable binary renaming and `Info.plist` synchronization against non-standard bundle layouts, missing plists, or corrupted binaries.
  - Gracefully falls back to standard execution paths with clear warning logs instead of aborting the cloning pipeline.
  - Added comprehensive test suites covering malformed bundles and fallback scenarios.

### 🎨 Wizard Icon Preview Null-Safety Guard
- **Interface Stability**:
  - Added null-safety check in `WizardWindow` icon preview loader to prevent edge-case UI exceptions when scanning apps with incomplete metadata.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Test suite expanded to **645 automated tests** with a 100% pass rate.

---

## [v2.1.0] - 2026-09-17

### 🚀 Distinct Process Names for Hard Clones & Proxy Rule Routing
- **Process-Based Network Proxy Routing**:
  - Hard clones now generate unique executable binary names and synchronized `CFBundleExecutable` entries (e.g. `<AppName>_<clone_name>`), enabling distinct macOS process identification.
  - Full support for granular, per-clone proxy routing rules in proxy managers such as Clash, Surge, Loon, Stash, and Quantumult X (e.g., `PROCESS-NAME,<CloneProcessName>,<ProxyGroup>`).
  - Robust handling of Electron and Chromium helper apps, preventing executable path collisions while maintaining IPC communication integrity.
  - Seamlessly preserves custom process names and custom icons during clone editing, updates, or regeneration.

### 🎨 Custom Application Icons in Cloning Wizard
- **Personalized Visual Identity**:
  - Added custom icon selection in `WizardWindow`, allowing users to assign custom `.icns` or `.png` graphics during clone creation.
  - Live icon preview in the wizard interface with one-click restore to original app icon.
  - Native icon replacement and format conversion in `Contents/Resources/`, maintaining custom icons across clone lifecycles.
  - Localized UI labels and buttons across all 9 supported languages.

### 🔄 Sidebar Bottom Auto-Update Control
- **Streamlined Update Experience**:
  - Relocated the update checker from Settings to the bottom of the navigation sidebar for immediate visibility and access.
  - Integrated animated refresh icon, live version feedback, and inline percentage progress bar for downloads.
  - Simplified Settings view, focusing purely on application preferences.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Added unit and integration tests for process renaming, helper path preservation, icon updates, and sidebar UI state (`test_process_names.py`, `test_update_icon.py`).
  - Test suite expanded to **642 automated tests** with 100% pass rate.

---

## [v2.0.0] - 2026-09-17

### 🏥 Environment Health Diagnostics (Doctor) & Directory Permissions
- **Deep Filesystem Permissions Verification**:
  - Enhanced diagnostic subsystem (`atbclone doctor` and GUI `DoctorView`) with real-time read/write permission verification for the Application Directory (`~/ATBClone/Apps`) and Data Storage Directory (`~/ATBClone/Data`).
  - Active probing using secure temporary tokens to detect permission denials before clone generation or app execution, preventing runtime crashes.
  - Granular reporting with distinct status badges, detailed filesystem error explanations, and actionable remediation commands (`chmod u+rwx <path>`).
  - Added `check_directory_access()`, `get_apps_dir()`, and `get_data_dir()` helper APIs in `core.config`.
  - Added localized diagnostic strings and actionable hints across all 9 supported languages.

### 📐 Documentation Portal Math Rendering & Formatting
- **KaTeX Mathematical Typography**:
  - Integrated KaTeX client-side math rendering engine across all 9 language editions of the documentation portal (`clone.aitobox.com`).
  - Optimized LaTeX display formula spacing and formatting within technical architecture deep dives.

### ⚡ Architectural Maturity & Quality Assurance (v2.0.0 Milestone)
- **High-Performance APFS Engine & Concurrency**:
  - Solidified the v2.0 foundation with APFS Copy-on-Write (`cp -Rc`) zero-space cloning, SIMD-accelerated binary analysis, and `flock`-backed atomic state persistence.
  - Expanded test suite with comprehensive unit and GUI tests for directory diagnostics (`test_cmd_doctor.py`, `test_config.py`, `test_probe_and_doctor_ui.py`).
  - All 614 automated test cases passing with a 100% success rate.

---

## [v1.9.0] - 2026-09-16

### ⚡ APFS Copy-on-Write (CoW) Cloning & Engine Performance
- **Instantaneous Zero-Copy Cloning**:
  - Implemented APFS Copy-on-Write (`cp -Rc`) cloning on macOS APFS volumes, enabling instantaneous cloning of gigabyte-scale applications with zero initial disk overhead.
  - Added robust fallback to standard recursive copying (`cp -R`) with automatic partial-destination cleanup to prevent directory nesting corruption on non-APFS volumes.
  - Integrated hardware SIMD pre-filtering in binary string probing, dramatically accelerating application argument and environment variable discovery.
  - Safe Mach-O binary skipping during wrapper script inspection and non-destructive entitlement pruning.

### 🔒 Concurrency Safety & Atomic State Persistence
- **Zero Race Conditions**:
  - Implemented cross-process `flock` file locking for clone state mutations, guaranteeing data consistency during concurrent clone operations and CLI commands.
  - Atomic configuration and state persistence using temporary files, forced filesystem sync (`fsync`), and secure `0o600` file permissions to prevent data corruption and unauthorized read access.
  - Thread-local `fake_pw` isolation in Cocoa interpose dynamic library hook, ensuring multi-threaded process safety.

### 🖥️ GUI / HIG Polish & System Stability
- **Interface & Lifecycle Hardening**:
  - Resolved `LogsView` memory leak by enforcing bounded buffer retention and threadsafe dispatching to the main Cocoa event loop.
  - Added lifecycle cleanup handler on application shutdown to deregister log listeners cleanly.
  - Restored secondary windows (Wizard, Clone Edit, Recipe Edit, Clone Detail) to standard window level (`0`), preventing dialogs from floating over other macOS applications.
  - Improved Dark Mode UI contrast, persistent custom `base_dir` configurations, and automatic Keychain proxy credential cleanup.
  - Standardized Chinese product branding to **ATB分身助手** across all interfaces and documentation.

### 📚 Multilingual Documentation Site & Quality Assurance
- **Official Documentation Portal (`clone.aitobox.com`)**:
  - Launched static documentation site powered by Zensical with automated GitHub Pages deployment.
  - Complete 9-language documentation matrix with localized UI walkthrough screenshots and synchronized navigation.
  - Expanded test suite with 22 new regression test cases (610 total tests, 100% pass rate).

---

## [v1.8.0] - 2026-09-13

### 📢 ATBCmder Promotion Card & [AD] Badge in Navigation Sidebar
- **Productivity Ecosystem Discovery**:
  - Added a clean, adaptive promotion card for ATBCmder (`https://aitobox.com/atbcmder`) in the navigation sidebar's flexible empty area.
  - Native macOS styling with rounded translucent container, prominent `[AD]` disclosure tag, high-resolution application icon, and external browser link button.
  - Dynamic i18n support across all 9 languages with instant real-time UI text refresh upon changing language preferences.
  - Dedicated asset resolution helper for `ATBCmderIcon.png` / `.icns` with robust fallback paths.

### 🛡️ CI/CD Release Notes Preservation & Packaging Hardening
- **Release Automation Resilience**:
  - Fixed an issue where `build_cli.sh` cleaning `dist/` wiped previously generated `dist/release_notes.md` before GitHub Releases upload.
  - Implemented automatic backup and restoration of release notes in `scripts/build_release_packages.sh`.
  - Added fallback release note extraction in `.github/workflows/release.yml` via `git tag` annotations and commit history to guarantee non-empty release documentation.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Coverage**:
  - Test suite expanded to 588 tests with 100% pass rate, covering sidebar promotion card layout, URL handling, dynamic translations, and packaging scripts.

---

## [v1.7.0] - 2026-09-13

### 🔄 In-App Auto-Update Subsystem & Silent Installer
- **End-to-End Automatic Updates**:
  - Implemented `UpdateService` to automatically query GitHub release manifest `latest.json` and detect newer versions via semantic version comparison.
  - Architecture-aware download resolution for Apple Silicon (arm64) and Intel (x86_64) DMG installers with streaming chunk downloads and live progress percentage reporting.
  - Automatic SHA256 checksum verification against release manifest metadata prior to installation, preventing corrupted or tampered downloads from executing.
  - Inherits configured system/application proxy settings (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) for seamless updates in restricted network environments.
  - Silent in-place installation: automatically mounts update DMG in an isolated temporary directory, replaces `ATBClone.app`, strips macOS Gatekeeper quarantine attributes (`xattr -cr`), and unmounts cleanly.

### ⚙️ GUI Settings View Update Flow
- **Visual Update Management**:
  - Added "Check for Updates" button and live status progression in `SettingsView`.
  - Multi-stage visual state transitions: Checking → Update available (with version & release notes) / Already up to date → Downloading (with percentage progress) → Installing → Update complete / Restart prompt.
  - User-friendly error reporting for network timeouts, HTTP issues, and checksum mismatches.

### 🌐 Comprehensive Multilingual Translations
- **Full i18n Coverage**:
  - Added localized strings across all 9 supported languages for update controls, status indicators, and notification dialogues.

### 📦 CI/CD Manifest Generation (`latest.json`)
- **Automated Release Metadata**:
  - Enhanced `scripts/build_release_packages.sh` to extract release notes, compute DMG SHA256 checksums, and generate `dist/latest.json`.
  - Updated `.github/workflows/release.yml` to upload `latest.json` to GitHub Releases with automated retry resilience.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Coverage**:
  - Test suite expanded to 585 unit, service, GUI, and CI packaging tests with a 100% pass rate.

---

## [v1.6.0] - 2026-09-13

### 🪟 Tray-to-Quit Deadlock Elimination & Lifecycle Hardening
- **Reliable Process Termination**:
  - Resolved a deadlock where clicking "Quit" from the macOS system tray icon or Dock right-click menu could freeze the application and fail to terminate while minimized to tray.
  - Introduced `_is_exiting` guard flag on `ATBCloneApp`, ensuring `_on_window_close` never intercepts or blocks shutdown sequences.
  - Fixed re-entrancy issue by removing premature `set_macos_dock_visible(True)` calls during `exit_application()`, eliminating redundant activation policy transitions in Cocoa run loop before termination.
  - Hardened both Dock quit (`_on_app_exit`) and tray quit (`exit_application`) lifecycles, guaranteeing immediate, clean teardown.

---

## [v1.5.1] - 2026-09-13

### 💬 KakaoTalk Built-in Application Recipe
- **Native Multi-Instance Support**:
  - Added built-in recipe for KakaoTalk (`com.kakao.KakaoTalkMac`) using Cocoa hard-clone strategy, sandbox stripping, and isolated data directories (`HOME`/`TMPDIR`).
  - Expanded built-in recipe collection to 34+ applications.
  - Documented verification scope (concurrent execution and notification features verified).

### 🚀 Automated GitHub Actions arm64 Release Workflow
- **Continuous Deployment & Packaging Automation**:
  - Added `.github/workflows/release.yml` automating release artifact generation upon pushing version tags (`v*`).
  - Builds and packages both standalone CLI archive (`ATBCloneCli-arm64.tar.gz`) and GUI installer (`ATBClone-*.dmg`) with SHA256 checksums.
  - Added `scripts/build_release_packages.sh` for unified packaging of release artifacts.
  - Fixed bash `set -u` unbound variable error on empty array expansion in `scripts/build_cli.sh` and `scripts/build_release_packages.sh`.

### 🛡️ Build Scaffolding & Network Resilience
- **Incomplete Build Recovery**:
  - Enhanced `scripts/build_gui.sh` scaffolding integrity checks to verify `Python.framework`, `ATBClone` executable, and `Stub`.
  - Automatically cleans and recreates corrupted or partial scaffolds caused by poor network downloads.

### 🔒 Security Policy (SECURITY.md)
- **Vulnerability Disclosure Guidelines**:
  - Added `.github/SECURITY.md` establishing private vulnerability reporting channels, in-scope components, and response SLAs.

### 🧪 Quality Assurance & Test Suite Expansion
- **Comprehensive Coverage**:
  - Expanded test suite to 561 unit, recipe, GUI, and packaging tests with a 100% pass rate.

---

## [v1.5.0] - 2026-09-10

### 🔐 Proxy Authentication & Keychain Secure Storage
- **Authenticated Proxy Support**:
  - Enhanced `ProxyConfig` model with `username` and `password` fields, supporting authenticated SOCKS5 and HTTP proxies.
  - Implemented `atbclone.core.keychain` module to securely store and retrieve proxy passwords via the macOS Keychain (`security` CLI / Keychain Services), preventing credentials from being saved in plaintext.
  - Added `--proxy-username` and `--proxy-password` CLI options with interactive secure password entry across `clone`, `update`, and `wizard` commands.
  - Integrated proxy credential inputs, password visibility toggles, and Keychain security controls into GUI Clone Wizard (`WizardWindow`), Clone Edit (`CloneEditWindow`), and Global Settings (`SettingsView`).
  - Integrated credential redaction (`redact_url_credentials`) across `clone_inspector`, CLI `list`, and GUI card/detail views to prevent password leakage in terminal output and UI logs.

### 🛠️ Xcode / CLT Toolchain Dynamic Probing
- **Compiler Compatibility & Auto-Adaptation**:
  - Implemented dynamic toolchain probing mechanism `_resolve_clang_command` in `CloneEngine`.
  - Automatically pairs `xcrun --sdk macosx clang` with the active macOS SDK sysroot, resolving compilation and linking failures caused by architecture target discrepancies (such as `arm64e.x1-macos`) under beta Xcode and Command Line Tools.

### 💼 Enterprise WeChat (WeCom) Built-in Recipe
- **Out-of-the-Box Multi-Instance Support**:
  - Added built-in recipe for Enterprise WeChat / WeCom (`com.tencent.WeWorkMac`), supporting isolated data directories and environment variable redirection.

### 🛡️ Security Hardening & Input Injection Defense
- **Centralized Validation & Anti-Tamper Guard**:
  - Introduced `atbclone.validation` module enforcing strict whitelists for Bundle IDs (`^[A-Za-z0-9][A-Za-z0-9._-]*$`), environment variable keys, proxy parameters, and clone name path-traversal prevention.
  - Enabled `validate_assignment = True` in Pydantic models `Recipe` and `ProxyConfig` to block attribute assignment bypasses.
  - Established `CloneTask.__post_init__` as a unified validation chokepoint across CLI, GUI, and update workflows.
  - Added anti-tamper deletion guard (`validate_deletion_target`) preventing destructive removal of system directories (`/System`, `/usr`, `/Library`), `$HOME` root, shallow paths, or non-.app targets.
  - Enforced `0600` POSIX permissions on `clones.yaml`.
  - Hardened shell script generation in clone engines using `shlex.quote` and metacharacter escaping (`$`, backticks, double quotes).

### 🧪 CI/CD Automation & Quality Assurance
- **Automated Testing & Expanded Test Suite**:
  - Added GitHub Actions automated CI testing workflow (`.github/workflows/test.yml`) on macOS runners restricted to Python 3.12.
  - Added standard PR template and CI build status badges to documentation.
  - Expanded automated test suite to 554 unit, GUI, security, and integration tests with a 100% pass rate.

---

## [v1.4.0] - 2026-09-05

### 🪶 Feishu / Lark Multi-Instance Isolation & Process Singleton Hook (Fix #7)
- **Private Data Redirection & Singleton Lock Isolation**:
  - Implemented specialized Cocoa & POSIX path hook dylib (`libatbclone_feishu_hook.dylib`) for Feishu/Lark (`com.electron.lark`).
  - Interposes `NSSearchPathForDirectoriesInDomains` and filesystem path resolution, redirecting `LarkShell`, `SingletonLock`, and `SingletonSocket` to the clone's private data directory.
  - Automatically strips `CFBundleURLTypes` in `Info.plist` to eliminate system URL scheme registration collisions.
  - Strictly scoped to Feishu/Lark recipes with zero impact on other cloned apps.

### 🤖 OpenAI ChatGPT Desktop & Codex Account Isolation
- **Independent Login Sessions & Deep-Link Sanitization**:
  - Introduced `patch_chatgpt_isolation` and injected `libatbclone_chatgpt_hook.dylib` to isolate Cocoa Application Support and Caches for ChatGPT Desktop (`com.openai.chat`).
  - Resolved `CODEX_HOME` initialization issue where the host's `~/.codex/auth.json` was inadvertently copied, ensuring completely isolated account tokens.
  - Stripped `CFBundleURLTypes` from ChatGPT clones to prevent deep-link protocol hijacking.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 485 unit, engine, recipe, and GUI integration tests with 100% pass rate.

---

## [v1.3.0] - 2026-09-05

### 🔬 Mach-O Headroom Probing & Safety Verification
- **Static Binary Header Inspection**:
  - Added `_check_macho_injection_headroom` to inspect available padding between Mach-O load commands (`sizeofcmds`) and the first section before modifying binaries.
  - Guarantees binary integrity by preventing corruption on applications with tightly packed Mach-O headers.

### 🎛️ Configurable Injection Strategy (`auto`, `dylib`, `launcher`)
- **Flexible Interposition Architecture**:
  - Added `injection_strategy` configuration across Recipe models, CloneTask, CloneRecord, CLI (`--injection-strategy`), and GUI (Clone Wizard, Recipe Editor).
  - **Auto mode** (`auto`): Intelligently probes Mach-O headroom for native Cocoa apps; injects dynamic libraries when headroom is sufficient, or gracefully falls back to native Mach-O C launcher with an explanatory notice.
  - **Dylib mode** (`dylib`): Enforces dynamic library injection, raising a descriptive `CloneError` if headroom is inadequate or binary architecture is unsupported.
  - **Launcher mode** (`launcher`): Forces native Mach-O C launcher wrapper without modifying application binaries.
  - Real-time display of the actual executed injection mode in `CloneDetailWindow` and CLI `inspect`.

### 📚 Comprehensive Documentation Updates
- **In-Depth Guides & Architecture Docs**:
  - Fully updated user manuals in `docs/guide/` (both English and Simplified Chinese) and READMEs with detailed explanations of injection strategies, dylib interception mechanisms, and headroom probing.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 479 unit, engine, probe, and GUI integration tests with 100% pass rate.

---

## [v1.2.1] - 2026-09-05

### 🧩 Decoupled Dylib Injection via @executable_path (Fix #6)
- **Robust Dynamic Library Interposition**:
  - Migrated dynamic library injection in `HardCloneEngine` from `@rpath` to `@executable_path/../Frameworks/libatbclone_env.dylib`.
  - Completely decouples dylib loading from target binaries' `LC_RPATH`, eliminating launch crashes and dyld symbol resolution failures on applications with non-standard or stripped rpath configurations (e.g., WeChat 4.x and custom Cocoa bundles).
  - Added fallback symlink generation in `Contents/Frameworks/ld/` when an `ld` directory structure is present.

### ⚙️ Automated Build Intermediate Artifacts & Info.plist Synchronization
- **Zero-Drift Version Alignment**:
  - Enhanced `scripts/manage_version.py` with native `PlistVersionTarget` via `plistlib` to automatically track and update `Info.plist` (`CFBundleShortVersionString` & `CFBundleVersion`) and `installer/resources/welcome.html`.
  - Added build intermediate artifact inspection and drift detection to `scripts/manage_version.py --show`.
  - Hardened `scripts/build_gui.sh` to guarantee both short and internal bundle versions are synchronized during GUI packaging.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 468 unit, engine, version management, and GUI integration tests with 100% pass rate.

---

## [v1.2.0] - 2026-09-02

### 🔔 Native Dylib Injection for macOS Notifications & Menu Bar Status Items
- **Notification Center & Tray Item Resolution (Fix #5)**:
  - Enabled native dynamic library (`.dylib`) interpose injection in `HardCloneEngine`.
  - Interposes NSUserNotificationCenter and NSStatusItem APIs, resolving missing macOS notification banners and menu bar tray status items for hard cloned applications.

### 🌓 Dynamic Dark Mode Awareness & Visual Theme Polish
- **System Appearance Tracking (Fix #4)**:
  - Added real-time macOS system appearance tracking to dynamically adapt GUI theme tokens when toggling between Dark and Light modes.
- **Card Layout & Contrast Improvements**:
  - Optimized card layout grid spacing and enlarged default application window width for improved readability.
  - Enhanced text contrast in Logs and Release Notes windows, meeting WCAG 2.1 AA legibility standards.

### 📖 Documentation & Screenshot Updates
- **Path Standards & Asset Refreshes**:
  - Updated default clone installation path across documentation to `~/ATBClone/Apps`.
  - Refreshed high-resolution GUI application screenshots in documentation and asset directories.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 462 unit, engine, recipe, theme, and GUI integration tests with 100% pass rate.

---

## [v1.1.1] - 2026-08-30

### 🧹 Automatic Stale Framework Version Pruning
- **Disk Optimization & Code Signing Verification**:
  - `HardCloneEngine` now automatically prunes orphaned/stale framework versions inside `Contents/Frameworks/*.framework/Versions/` (often left behind by in-place updates of Google Chrome, Chromium, and Electron apps).
  - Eliminates `"embedded framework contains modified or invalid version"` errors during codesign verification while saving hundreds of megabytes of disk space per cloned application.

### 🛡️ Deep Entitlements Sanitization with Python Plistlib
- **Atomic Extraction & Security Policy Filtering**:
  - Upgraded entitlements extraction to use secure atomic temporary files (`${TMPDIR:-/tmp}/atb_ent_XXXXXX`).
  - Integrated Python `plistlib` filtering to reliably purge restricted Apple developer, application-group, iCloud, and sandbox entitlement prefixes (`com.apple.developer.`, `keychain-access-groups`, `com.apple.security.application-groups`, `com.apple.security.app-sandbox`).
  - Multi-stage recursive code signing across dynamic libraries, Mach-O binaries, frameworks, and embedded helper apps.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 455 unit, engine, recipe, prober, and GUI integration tests with 100% pass rate.

---

## [v1.1.0] - 2026-08-29

### 🤖 First-Class AI Client & LLM Tool Ecosystem Support
- **Claude Desktop & Claude Code Multi-Instance Support**:
  - Automatically injects `CLAUDE_CONFIG_DIR`, replicates and isolates `~/.claude` and `~/.claude.json` configuration directories per clone.
  - Preserves `CFBundleName` across cloned bundles to ensure Claude helper processes locate the host application without lookup crashes.
- **Google Antigravity & Gemini Ecosystem**:
  - Injects `GEMINI_HOME` and `ANTIGRAVITY_HOME` environment variables, isolating `~/.gemini` data directories.
- **OpenAI ChatGPT & Codex CLI**:
  - Injects `CODEX_HOME` and replicates `~/.codex` configuration directories for simultaneous multi-account execution.

### 🔑 Automatic macOS Keychain Symlinking
- **Keychain Redirection & Crash Prevention**:
  - Automatically establishes symlinks to `Library/Keychains` when `HOME` environment redirection is enabled, eliminating missing keychain alerts, login item crashes, and credential storage errors.

### 🛡️ AMFI Entitlements Sanitization & Hardened Runtime Security
- **Ad-Hoc Signing Stability on macOS Sonoma & Sequoia**:
  - Automatically sanitizes restricted team-scoped entitlements (`com.apple.application-identifier`, `com.apple.developer.team-identifier`, `keychain-access-groups`) during ad-hoc re-signing.
  - Prevents Apple Mobile File Integrity (AMFI) `SIGKILL` termination on embedded helper processes.

### 🚀 ProcessSingleton Mach-O Patching Generalization
- **Broad AI & Electron Multi-Instance Support**:
  - Generalized Mach-O ProcessSingleton patching and injected `--user-data-dir` arguments across AI client recipes to prevent single-instance locks.

### 🧪 Comprehensive Quality Assurance
- **Expanded Test Suite**:
  - Automated test suite expanded to 453 unit, engine, recipe, prober, and GUI integration tests with 100% pass rate.

---

## [v1.0.2] - 2026-08-26

### 🛡️ Enhanced Sandbox Stripping & Hard Clone Stability
- **Universal Sandbox Stripping for Hard Clones**:
  - Configured `strip_sandbox: true` across recipes utilizing the Hard Clone strategy, preventing sandbox container permission deadlocks and permission conflicts on modified Mach-O bundles.
  - Enhanced WeChat (微信) hard clone configuration with guaranteed runtime directory structures (`Caches`, `Containers`, `Preferences`) in wrapper scripts.

### 📚 Recipe Curations & Upstream Limitation Documentation
- **Built-in Recipe Refinement**:
  - Removed experimental WeCom (企业微信) built-in recipe due to upstream CEF deep IPC anti-multi-instance architectural constraints, and added clear troubleshooting documentation.
  - Documented best practices for third-party application multi-instance configurations and recipe authoring.

### 🧪 Comprehensive Quality Assurance
- **Full Test Coverage**:
  - Verified 443 automated unit, recipe, engine, and GUI integration tests with 100% pass rate.

---

## [v1.0.1] - 2026-08-26

### 🎨 Apple Design HIG Audit & Visual Refinements
- **macOS Human Interface Guidelines Compliance**:
  - Comprehensive Apple Design HIG audit across all desktop views and dialogs.
  - Eliminated distracting emoji decorations in favor of native SF Pro typography hierarchies and clean iconography.
  - Enhanced sidebar navigation with native Cocoa selection highlights.
  - Polished light and dark mode color contrast ratios exceeding WCAG 2.1 AA legibility standards.
  - Improved empty states, card shadows, window drag responsiveness, and consistent widget padding.

### 📜 Reverse Chronological Logs & UI Layout Fixes
- **Real-Time Logs Enhancement (`LogsView`)**:
  - Configured log display to render in reverse chronological order (newest log entries at the top), significantly improving live diagnostic efficiency.
- **Multilingual Button Width Adaptations**:
  - Removed rigid fixed widths from Refresh and Browse buttons across windows to prevent text clipping in English, German, French, Russian, and Spanish.

### 🛡️ Clone Engine Resilience & Extended Attribute Toleration
- **Bundle Permissions & `xattr` Error Handling**:
  - Automatically enforces user write permissions (`chmod -R u+w`) on cloned app bundles prior to Mach-O modification and code signing.
  - Added fault-tolerant error handling for macOS extended attribute clearance (`xattr -cr`) on read-only system snapshots or protected files, eliminating cloning failures.

### 🧪 Test Suite & Quality Assurance
- **Expanded Coverage**:
  - Automated test suite expanded to 443 unit, engine, and GUI integration tests with 100% pass rate.

---

## [v1.0.0] - 2026-08-24

### 🚀 Official 1.0.0 Milestone Release
- **Production-Ready macOS App Cloning**:
  - ATBClone reaches version 1.0.0, establishing a complete, mature, and zero-compromise application cloning ecosystem for macOS (Apple Silicon & Intel).
  - Offers seamless dual-engine architectures: zero-disk-overhead Soft Clones (CLI-wrapper & bundle virtualization) and completely isolated Hard Clones (Mach-O binary manipulation, deep signing, container virtualization).

### 🧬 Deep CEF (Chromium Embedded Framework) Patching & WeCom Support
- **Hybrid Framework Multi-Instance Engine**:
  - Implemented scoped Chromium Embedded Framework (CEF) binary patching specifically designed for complex enterprise hybrid applications such as WeCom (企业微信).
  - Resolved `GpuDataManager` FATAL crashes across helper subprocesses and sanitized nested helper bundle identifiers (`.helper.atbclone.X`).
  - Integrated symlink whitelists and disabled internal sandbox collisions to guarantee reliable multi-instance execution.

### 🛡️ Full-Bundle Recursive Re-Signing & Entitlements Sanitization
- **Nested Binary & Framework Security**:
  - `HardCloneEngine` now performs thorough recursive re-signing across all nested binaries, embedded Frameworks, Helper apps, XPC services, and dynamic libraries (`.dylib`).
  - Preserves JIT and hardened runtime entitlements while generating clean temporary entitlements outside bundle structures to prevent code signature verification pollution.
- **Framework ProcessSingleton Binary Patching**:
  - Introduced `patch_framework_singleton` recipe field to dynamically patch framework-level process singleton locks directly in Mach-O binary structures without unstable dynamic library interposing.

### 📋 Enhanced Detail Views & Native Clipboard Integration
- **Diagnostic Export**:
  - Re-architected `CloneDetailWindow` using multiline Cocoa text views and direct `NSPasteboard` integration for selectable text and instantaneous markdown diagnostic summary exporting.

### 🧪 Comprehensive Quality Assurance
- **Full Test Coverage**:
  - Automated test suite expanded to 441 unit, engine, recipe, prober, and GUI integration tests with 100% pass rate.

---

## [v0.9.9] - 2026-08-24

### 📋 Selectable Text & "Copy All Details" in Clone Details Window
- **Interactive Information Extraction**:
  - Enabled Cocoa native text selectable mode across all labels in `CloneDetailWindow` so users can highlight and copy any individual path, bundle ID, or argument directly.
  - Added a dedicated "Copy All Details" button in the footer to copy a complete markdown-formatted diagnostic report of the clone to the clipboard with visual feedback.

### 🎨 macOS Native UI Design & Token Refinements
- **Theme & Component Optimization**:
  - Polished color palette tokens in `Theme` for light and dark modes (`BG_APP`, `BG_CARD`, `BG_HOVER`, `BORDER`, `TEXT_PRIMARY`, `TEXT_MUTED`, `ACCENT`).
  - Improved card containers, rounded borders, and consistent widget spacing across `CloneListView`, `RecipeListView`, `ProbeView`, `DoctorView`, `SettingsView`, and dialog windows.

### 📖 Comprehensive Multilingual User Manual (`docs/guide/`)
- **Complete End-to-End User Documentation**:
  - Published comprehensive user manuals in English (`docs/guide/en/`) and Simplified Chinese (`docs/guide/zh-cn/`).
  - Covers Chapter 1 (Basic Operations & Lifecycle), Chapter 2 (Advanced Custom Recipes), Chapter 3 (Under the Hood & Framework Architecture), and Chapter 4 (FAQ, Troubleshooting, & Diagnostics).

### 🧪 Test Suite & Quality Assurance
- **Extended Test Coverage**:
  - Automated test suite expanded to 431 tests with 100% pass rate.

---

## [v0.9.8] - 2026-08-24

### 🔒 Sandbox Entitlements Extraction & Hard Clone Stability
- **Source App Entitlements Preservation**:
  - Enhanced `HardCloneEngine` to extract and preserve original entitlements directly from source Mach-O binaries via `codesign -d --entitlements :-`.
  - Added robust validation to guard against generating empty or corrupt entitlements during ad-hoc and Developer ID re-signing.
- **Built-in Recipes Sandbox Container Isolation**:
  - Refined built-in recipe configurations by enforcing `strip_sandbox: false` across hard-clone applications (including WeChat, QQ, WeWork, WPS Office, LINE, Skype, and CapCut).
  - Ensures complete sandbox container isolation (`~/Library/Containers/<new_bundle_id>`) to prevent credential leakage and cross-instance interference.

### 📚 Documentation & Schema Modernization
- **Multilingual Documentation Updates**:
  - Synchronized English (`README.md`) and Simplified Chinese (`README_zh.md`) documentation with current schema standards, including `app_type`, `strip_sandbox`, runtime architecture classifications, and CLI/GUI workflows.

### 🧪 Test Suite & Quality Assurance
- **Robust Verification**:
  - Verified all 428 unit, core engine, and GUI integration tests pass with 100% success rate.

---

## [v0.9.7] - 2026-08-24

### 🔍 Intelligent Application Architecture Detection & Language Adaptation
- **`app_type` Architecture Recognition**:
  - Introduced `app_type` field (`electron`, `chromium`, `qt`, `flutter`, `native_cocoa`, `java`, `unknown`) to the Recipe model.
  - Automatically recognizes application runtime frameworks via `AppProber.detect_app_type` by inspecting bundle frameworks, dylibs, and JVM structures.
  - Standardized all 34 built-in recipes with explicit `app_type` and `strip_sandbox` configurations.
- **Framework-Adaptive Language Injection**:
  - Dynamically injects locale flags customized per runtime framework (`--lang=` for Chromium/Electron, `-AppleLanguages` for Native Cocoa, `-user.language` for Java).

### 🧬 Mach-O Binary Argument Probing & Validation
- **Intelligent Data Directory Probing**:
  - Implemented `BinaryArgumentProber` to scan Mach-O executable string tables, automatically extracting supported user data directory CLI flags (`--user-data-dir`, `--profile-directory`, `--datadir`, etc.) for unknown applications.
- **Launch Argument Validation**:
  - Added `LaunchArgumentValidator` to prune unsupported or conflicting CLI flags during clone creation, preventing application crashes.

### 📋 Clone Injected Parameters Inspection & Copy
- **`CloneInspector` & Details View Enhancement**:
  - Implemented `CloneInspector` to parse and extract runtime injected environment variables, proxy settings, language overrides, and launch flags from clone bundles.
  - Added an "Injected Parameters" card in `CloneDetailWindow` with a one-click copy button and visual feedback.

### ⚙️ Recipe Editor Window Advanced Customization
- **GUI Recipe Editing (`RecipeEditWindow`)**:
  - Added advanced configuration fields including application framework type selection, launch arguments editor, proxy settings, environment variables, and symlink whitelists.

### 🧪 Test Suite Expansion
- **Comprehensive Coverage**:
  - Expanded automated test suite to 428 unit and GUI integration tests.

---

## [v0.9.6] - 2026-08-24

### 🖱️ Native Cocoa Table Header Sorting
- **Interactive Column Sorting in Lists**:
  - Implemented native Cocoa `NSTableViewHeaderView` click-to-sort patch supporting column sorting across `CloneListView` and `RecipeListView`.
  - Supports bidirectional sorting (ascending / descending) with visual sort indicators on table headers and toolbar sort controls synchronization.
  - Automatically preserves active item selection across sort operations.

### 📦 Multi-Selection & Batch Operations
- **Batch Clones Management (`CloneListView`)**:
  - Added multi-row selection support (`multiple_select=True`) with dynamic toolbar button state management.
  - Supports batch clone updates and batch removals with purge data confirmation dialogs.
- **Batch Recipe Deletion with Smart Protection (`RecipeListView`)**:
  - Multi-selection deletion for custom recipes.
  - Scenario-based confirmation dialogs: protects builtin read-only recipes, alerts users when mixing custom and builtin recipes, and accurately reports batch deletion progress.
  - Integrated busy state locking to prevent concurrent operations during batch executions.

### 🛠️ Xcode Command Line Tools Diagnostic & Doctor View Enhancement
- **Startup Diagnostic Checks**:
  - Added automated environment checks for Xcode Command Line Tools readiness (`xcode-select -p`, `codesign`, `lipo`, `otool`, `install_name_tool`).
  - Provides clear diagnostic guidance and installation commands in the Doctor View when tools are missing.

### ℹ️ Standard macOS About Dialog Metadata
- **Cocoa About Dialog Fix**:
  - Properly mapped version numbers, app name, and copyright metadata in the standard macOS "About ATBClone" dialog.

### 🧪 Test Suite Expansion
- **Comprehensive Coverage**:
  - Expanded automated test suite to 369 unit and GUI integration tests.

---

## [v0.9.5] - 2026-08-23

### 📝 Auto-Wrapping `WrappingLabel` Component & Text Formatting
- **Multiline Text Wrapping Support**:
  - Implemented the `WrappingLabel` component to solve macOS Cocoa Toga single-line text constraint limitations.
  - Automatically calculates dynamic intrinsic height based on the container width (`cellSizeForBounds_`) while leaving width unconstrained, completely preventing long pathnames and text from expanding windows horizontally.
- **Prober & Detail View Formatting**:
  - Applied `WrappingLabel` across `ProbeView` (Prober analysis reports, compatibility evaluations, sandbox status), `CloneDetailWindow` (launch arguments, bundle id, data directories), and `WizardWindow` (strategy descriptions and advice).

### 🧪 Test Hermeticity & State Isolation
- **Dynamic Configuration & Test Isolation**:
  - Enhanced `StateManager` and `RecipeLoader` to dynamically evaluate configuration paths at runtime rather than module import time.
  - Ensured unit tests remain strictly hermetic and isolated from local user state and custom recipe files.
- **Testing**:
  - Expanded automated test suite to 347 unit and GUI integration tests.

---

## [v0.9.4] - 2026-08-23

### 📁 Visible Default Data Directory Migration (`~/ATBClone`)
- **Intuitive User Data Management**:
  - Migrated the default ATBClone root directory from hidden `~/.atbclone` to user-accessible `~/ATBClone` (including `~/ATBClone/Data/`, `~/ATBClone/clones.yaml`, and logs).
  - Makes managing, backing up, and inspecting clone storage and configurations straightforward via macOS Finder and Terminal.

### 🏷️ Exact Application Display Name Enforcement & Localization Override
- **Consistent Bundle Naming**:
  - Enhanced both `SoftCloneEngine` and `HardCloneEngine` to clean up localized strings (`InfoPlist.strings`) and remove `LSHasLocalizedDisplayName` within cloned app bundles.
  - Ensures Finder, Dock, Spotlight, and Activity Monitor strictly display the custom clone display name instead of falling back to system-localized default titles.

### 🔄 Instant LaunchServices Registration
- **Automated Cache Refresh**:
  - Automatically registers newly generated or updated clones with macOS LaunchServices (`lsregister -f`), immediately reflecting icon and metadata updates across Finder, Dock, and Spotlight without requiring system reboots.

### 📦 Test Suite & Documentation
- **Updated References**:
  - Reflected new `~/ATBClone` default path across CLI documentation, GUI settings, and all 341 unit and integration tests.

---

## [v0.9.3] - 2026-08-21

### 🛡️ Enhanced App Inspection & Wizard Validation for iOS Wrapper Apps
- **Interactive Wizard Pre-check & Error Dialog**:
  - Upgraded `AppInspector.inspect_app` to detect iOS-on-Mac (Designed for iPad/iPhone) wrapper applications directly during file selection or drag-and-drop.
  - In the GUI Creation Wizard (`WizardWindow`), selecting an unsupported iOS wrapper application now immediately triggers a localized warning dialog and resets the input, preventing invalid workflows upfront.

### 🍏 Clean macOS Exit & Cocoa Memory Target Teardown
- **Crash Prevention on Application Termination**:
  - Enhanced `TrayService.disable()` and `ATBCloneApp.exit_app()` to safely unbind Cocoa status item targets and selectors, eliminating dangling Objective-C pointers during shutdown.
  - Implemented clean Cocoa event loop termination (`NSApp.terminate_` / `os._exit(0)`), completely resolving crash-on-exit / segmentation fault issues when quitting via the Menu Bar tray or `Cmd+Q`.

### 📦 Test Suite Expansion
- **Comprehensive Testing**:
  - Expanded test coverage to 341 automated unit and GUI integration tests.

---

## [v0.9.2] - 2026-08-21

### 🍏 Dynamic macOS Dock Icon Hiding & System Tray Polishing
- **Automatic Dock Icon Management**:
  - Implemented dynamic macOS Dock icon visibility management via AppKit activation policies (`NSApplicationActivationPolicy`).
  - When minimizing or closing the window to the system tray (`minimize_to_tray` enabled), the Dock icon is automatically hidden from the macOS Dock (`NSApplicationActivationPolicyAccessory`).
  - When restoring the window from the menu bar tray, the Dock icon seamlessly reappears (`NSApplicationActivationPolicyRegular`) with instant focus.
- **Dock Reopen Handler**:
  - Added native `AppDelegate` patch for `applicationShouldHandleReopen:hasVisibleWindows:` to smoothly restore and focus the main window when clicking the application in macOS Finder or Dock.

### 📦 Asset Footprint Optimization & Testing
- **Optimized Image Resources**:
  - Compressed and optimized application icon assets (`logo.icns` and `logo.png`), reducing bundle overhead.
- **Testing**:
  - Expanded automated test suite to 338 unit and GUI integration tests.

---

## [v0.9.1] - 2026-08-21

### 🛡️ iOS-on-Mac Wrapper Application Detection & Safe Rejection
- **Graceful Unsupported Architecture Handling**:
  - Enhanced `AppProber`, `SoftCloneEngine`, and `HardCloneEngine` to accurately identify iOS/iPadOS wrapper applications designed for Apple Silicon (apps containing `Wrapper/` or `UIDeviceFamily` with `LSRequiresIPhoneOS=True`).
  - Gracefully rejects cloning iOS-on-Mac wrapper applications with clear, localized error prompts (`error_ios_wrapper_unsupported`) across CLI (`atbclone clone`, `atbclone wizard`) and GUI Creation Wizard, preventing corrupted bundle generation and launch failures.

### 🎨 Automated Icon Resource Pipeline in Packaging Scripts
- **Dynamic `.icns` Generation**:
  - Added automated `.icns` compilation via `sips` and `iconutil` in `scripts/build_gui.sh` during macOS DMG and app bundle generation.
  - Enhanced asset inclusion and integrity verification in packaging workflows.

### 🌐 Multi-Language Localization
- **Localized Error Diagnostics**:
  - Added localized prompt messages for unsupported iOS wrapper apps across all 9 supported languages.
- **Testing**:
  - Expanded test suite to 336 automated unit and GUI integration tests.

---

## [v0.9.0] - 2026-08-21

### 🌐 Per-Clone Independent Language & Locale Isolation
- **Custom Locale & Language Selection (`--language` / `--locale`)**:
  - Added support for running clones in dedicated languages independent from the host system macOS language and primary application settings.
  - CLI commands `atbclone clone` and `atbclone wizard` now support `--language` / `--locale` parameters, and the GUI Creation Wizard / Edit Dialog provide interactive language pickers.
  - Automatically injects `AppleLanguages` and `AppleLocale` macOS user defaults and environment variables into soft clone wrappers and hard clone binary launchers.
  - Added `atbclone.core.locale` helper supporting comprehensive language tag parsing, BCP-47 identifiers, and system locales.

### 🆔 Robust Multi-Instance Bundle ID Resolution
- **Collision-Free Clone Bundle Identifiers**:
  - Introduced `AppInspector.find_next_bundle_id` to dynamically scan active clone states and the file system, ensuring deterministic, collision-free Bundle IDs (`com.vendor.app.atb1`, `atb2`, etc.) when creating multiple instances of the same application.

### 🍏 System Tray Activation & Window Lifecycle Improvements
- **Seamless macOS Menu Bar Tray Experience**:
  - Fixed window activation, deminiaturization, and unhiding when restoring the main window from the system menu bar status item (`TrayService`).
  - Intercepted window close events (`Cmd+W` / red traffic light button) when "Minimize to System Tray" is enabled to cleanly hide the window to the tray rather than terminating.
  - Enhanced status item mouse event handling (left click, right click, and Ctrl+Click).

### ⚡ Clone Update Concurrency & Clean Destination Cleanup
- **Atomic Re-cloning**:
  - Resolved race conditions during clone update operations by enforcing thorough destination bundle cleanup before re-generation.
  - Fixed UI state synchronization and reactive card updates upon clone modification.

### 🎨 GUI Typography, Sizing & Documentation
- **Visual Polish**:
  - Optimized Cocoa table row heights (34px), typography scale, and dropdown selection text sizing to prevent clipping.
  - Added comprehensive download sections, GUI walkthrough guide, and screenshots to documentation.
- **Testing**:
  - Expanded automated test suite to 329 unit and GUI integration tests.

---

## [v0.8.0] - 2026-08-20

### 🎨 macOS Human Interface Guidelines (HIG) Visual Overhaul
- **Native Apple Design System & Accessibility**:
  - Fully overhauled the GUI design to adhere strictly to Apple Human Interface Guidelines: standardized native color palettes, typography scale (11pt–22pt), and comfortable spacing hierarchy.
  - Enhanced Cocoa table rendering via runtime patches (`patch_cocoa`): increased row height to 40px, modernized table headers, and enlarged cell font sizes for crystal-clear readability.
  - Enlarged input fields, dropdown selectors, switches, action buttons, and form labels across the Creation Wizard, Settings, and Detail/Edit dialogs.
  - Refined table action footers into compact native macOS toolbar buttons.
  - Switched default view mode to **List View** across all management views for dense and readable app inspection.

### 💾 Unified Storage Settings & Subdirectory Auto-Sync
- **Streamlined Storage Management**:
  - Reorganized SettingsView to consolidate root storage and path configurations. Modifying the Root Storage directory automatically and reactively updates all derived subdirectories (`clones.yaml`, `Data/`, `logs/`, `recipes/`).
  - Added real-time validation and directory existence status indicators.

### 🌐 HTTPS Proxy Protocol Support
- **Full HTTPS Proxy Integration**:
  - Added support for `https://` proxy schemes across Recipe validation models, CLI (`atbclone clone`, `atbclone wizard`), and GUI network configurations.

### 📦 Application Bundle & Packaging Improvements
- **Direct Module Entrypoint & DMG Enhancements**:
  - Added `src/atbclone/__main__.py` entrypoint allowing direct execution via `python -m atbclone`.
  - Enhanced GUI packaging script (`scripts/build_gui.sh`) with robust bundle integrity validation, resource verification, and DMG creation.
- **Testing**:
  - Expanded automated test suite to 304 unit and GUI integration tests.

---

## [v0.7.0] - 2026-08-20

### 🖥️ Native BeeWare Toga GUI Desktop Application
- **Modern Ice-Blue Graphical Interface**:
  - Introduced the full native macOS desktop application (`atbclone-gui`), built on BeeWare Toga.
  - Implemented responsive sidebar navigation and unified views: Clone Cards Grid (`ClonesView`), App Prober (`ProbeView`), Recipe Manager (`RecipesView`), Logs Viewer (`LogsView`), and Settings (`SettingsView`).
  - Interactive visual wizard for drag-and-drop cloning with real-time feedback.

### 🍏 Native macOS Menu Bar Tray Service & Window Minimization
- **System Menu Bar Tray Integration**:
  - Implemented native `NSStatusBar` & `NSStatusItem` Menu Bar icon (`TrayService`) with quick actions (Open Main Window, Create Clone, Quick Launch, Preferences, Quit).
  - Added "Minimize to System Tray" setting with seamless Cocoa selector registration and `NSWindowDelegate` notifications.

### 📖 GUI Multilingual Release Notes Viewer
- **Integrated Release Notes Window**:
  - Added a dedicated Release Notes viewer accessible directly from the Settings view.
  - Dynamic 9-language switcher dropdown allowing real-time Markdown rendering across all supported languages.

### 📝 Unified Operation Logging System
- **Thread-safe Logging & Live Stream**:
  - Implemented `atbclone.core.logger` with persistent file logging (`~/.atbclone/logs/atbclone.log`) and live memory broadcasting (`LogBroadcastHandler`).
  - Interactive GUI Logs view with live streaming, log level filtering, search, export, and disk log clearing.

### 📦 Enhanced Recipes & Testing
- **New Built-in Recipes**: Added official recipes for **Claude Desktop** (`com.anthropic.claudefordesktop`), **Telegram** (`ru.keepcoder.Telegram`), **Cursor**, and other popular tools.
- **Comprehensive Testing**: Upgraded test suite to 299 automated unit and GUI integration tests.

---

## [v0.6.0] - 2026-08-19

### 📂 Custom Data Directory Support
- **Customizable Clone Data Storage (`--data-dir`)**:
  - Added `--data-dir` option to `atbclone clone`, allowing users to specify custom locations for cloned app user data (e.g. external SSDs or custom workspaces).
  - Integrated custom data directory configuration into the interactive wizard (`atbclone wizard`).
  - Enhanced Recipe data models and engines to resolve dynamic custom data directory variables.

### 🗑️ Enhanced Clone Uninstallation & Cleanup (`atbclone remove`)
- **Safe Data Purging Controls**:
  - Added `--purge-data` flag to `atbclone remove` for automated complete deletion of clone bundle and associated user data directories.
  - Added `--keep-data` flag to preserve isolated data while uninstalling application bundles.
  - Interactive removal confirmation prompts now offer clear choices between preserving or purging data with safety warnings.
  - Enhanced handling of orphan data directories and permission diagnostics during removal.

### 🆔 Bundle ID Standardization & i18n
- **Standardized Bundle Identifier Generation**:
  - Added `AppInspector.generate_bundle_id` helper, standardizing clone bundle ID formatting across `clone`, `wizard`, and `update` commands.
- **Multilingual Support**:
  - Added full translation coverage for data directory prompts, remove confirmation dialogs, and purge status logs across all 9 supported languages.
- **Testing**:
  - Expanded automated test suite to 213 unit tests.

---

## [v0.5.0] - 2026-08-19

### 🔐 Apple Code Signing & Notarization Pipeline
- **Automated Hardened Runtime & Signing**:
  - Integrated Apple Developer ID Application code signing with Hardened Runtime (`--options runtime`), timestamping, and custom JIT / execution entitlements (`scripts/entitlements.plist`).
  - Added `scripts/notarize.sh` for one-command Apple Notarization (`xcrun notarytool submit --wait`) using Keychain API credentials (`--keychain-profile`).
  - Enhanced `scripts/build_cli.sh` and `scripts/release.sh` with `--sign-identity`, `--skip-sign`, and `--notarize` flags with automatic ad-hoc signing fallback.

### 🚀 Chromium Hard Clone & Launch Arguments Injection
- **Hard Clone Engine Support for `launch_args`**:
  - Upgraded `HardCloneEngine` to support dynamic `--user-data-dir={{ATB_DATA_DIR}}` argument injection into binary launch wrappers alongside environment variables.
  - Upgraded built-in recipes for **Google Chrome**, **Microsoft Edge**, and **Arc Browser** to `hard_clone` for complete app bundle duplication and isolated Dock/Finder identities.
- **CLI Strategy Override**:
  - Added `--strategy` option to `atbclone clone` (`--strategy hard_clone` / `--strategy soft_clone`) allowing users to explicitly override default recipe strategies.

### ⚡ Process Forwarding & Test Suite Expansion
- **Process Management**: Improved `SoftCloneEngine` launcher script to use standard `exec "$@"` argument forwarding.
- **Comprehensive Testing**: Expanded automated test suite to 199 unit tests covering code signing, notarization scripts, and strategy overrides.

---

## [v0.4.0] - 2026-08-19

### 🌐 Comprehensive 9-Language CLI & Documentation Ecosystem
- **Full CLI Internationalization Across 9 Languages**:
  - Expanded `atbclone.core.i18n` with full localization support for English, Simplified Chinese, Traditional Chinese, Japanese, Korean, German, French, Russian, and Spanish.
  - All interactive commands (`wizard`, `clone`, `probe`, `list`, `recipe`, `doctor`, `update`, `remove`, `version`) seamlessly render localized prompts, tables, and error diagnostics.
- **Multilingual Release Notes Architecture**:
  - Standardized release note documentation across all 9 supported languages under `docs/release/`.

### 🔄 Automated Release & Version Synchronization Pipeline
- **Automated 9-Language Release Notes Validation**:
  - Enhanced `scripts/manage_version.py` and `scripts/release.sh` with automated checks ensuring all 9 `docs/release/ReleaseNote*.md` files are synchronized and validated before creating release tags.
  - Added `--check-notes` validation flag in version manager to prevent missing release documentation.
- **Enhanced Test Suite**:
  - Upgraded automated test suite to 191 unit tests with full multi-language and release workflow coverage.

---

## [v0.3.0] - 2026-08-19

### 🌐 Internationalization & Multilingual Support
- **Automatic macOS System Language Detection**:
  - Integrated `atbclone.core.i18n` engine that automatically detects macOS system UI language preferences via `AppleLanguages` and `AppleLocale`.
  - Seamlessly switches CLI interactive wizards, prompts, table headers, and error logs between English and Chinese.
  - Added `ATBCLONE_LANG` environment variable override (`ATBCLONE_LANG=en` / `ATBCLONE_LANG=zh`) for manual language switching.
- **Multilingual Documentation**:
  - Standardized English as default `Readme.md` with full Chinese translation in `Readme_zh.md`.
  - Comprehensive Release Notes across 9 languages: English, Simplified Chinese, Traditional Chinese, Japanese, Korean, German, French, Russian, and Spanish.

### 🛠️ CLI & Build Improvements
- **Interactive Wizard i18n**: Fully translated `atbclone wizard` interactive prompts, display name customizations, custom icon pickers, and proxy configurations.
- **Standalone Binary**: Rebuilt `./dist/ATBCloneCli` using Nuitka with embedded multilingual resources and sandbox compatibility (`PYTHONNOUSERSITE=1`).
- **Comprehensive Test Suite**: Added `test_i18n.py` and upgraded all 186 unit tests to support bilingual assertions across test environments.

---

## [v0.2.0] - 2026-08-18

### 🚀 Major Features
- **Interactive Cloning Wizard (`atbclone wizard`)**:
  - Step-by-step CLI terminal guide with support for dragging and dropping `.app` paths.
  - Automatic clone name incrementing (e.g., `WeChat2`, `WeChat3`).
  - Support for custom application display names and custom `.icns` application icons.
  - Interactive network proxy setup (HTTP & SOCKS5) with authentication support.
- **Intelligent Deep App Prober (`atbclone probe`)**:
  - Automatically inspects Mach-O architectures (arm64, x86_64, Universal), frameworks (Electron, Flutter, Chromium, Qt, Cocoa), and code signing sandbox entitlements (`com.apple.security.app-sandbox`).
  - Dynamically determines the optimal cloning strategy (`hard_clone` vs `soft_clone`) for unlisted applications and outputs recommended Recipe YAMLs.
  - Integrated automatic fallback to prober in `atbclone clone` when no built-in recipe exists.
- **Standalone Binary Packaging**:
  - Added `scripts/build_cli.sh` to compile a zero-dependency, single-file native macOS arm64 binary (`dist/ATBCloneCli`) via Nuitka.

### ⚡ Improvements & Fixes
- Enhanced privilege elevation using native single-prompt macOS `osascript` authorization for `/Applications` output paths.
- Improved command line path escaping with `shlex.quote` to protect against spaces and special characters.

---

## [v0.1.0] - 2026-08-17

### 🌟 Initial Release
- **Dual-Engine Cloning Mechanism**:
  - **Hard Clone Engine**: Full App Bundle duplication, `Info.plist` modification, `HOME` / `TMPDIR` data directory isolation, optional App Sandbox stripping, and ad-hoc code re-signing.
  - **Soft Clone Engine**: Lightweight launcher wrapper for Chromium browsers and code editors with automated `--user-data-dir` and proxy injection.
- **18+ Built-in Recipes**:
  - Instant Messaging: WeChat, QQ, Telegram, LINE, Slack, Discord, Skype.
  - AI Clients: ChatGPT (Codex), Gemini, Antigravity, Antigravity IDE.
  - Browsers & Editors: Google Chrome, Microsoft Edge, Firefox, Arc, Cursor, VS Code, Zed.
- **CLI Commands**:
  - `clone`: Clone applications with optional custom names, directories, and proxies.
  - `list`: View all active clones with creation time, strategy, and proxy status in Rich tables.
  - `update`: Synchronize clones after main app updates while preserving user data.
  - `remove`: Delete clones with optional data directory purging.
  - `recipe`: List built-in recipes and inspect local recipe overrides.
  - `doctor`: Automated environment self-checks (`codesign`, `xcode-select`, `PlistBuddy`).
