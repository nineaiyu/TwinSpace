# TwinSpace Core Context

TwinSpace is a native macOS application cloning system that isolates application data, preferences, and processes while preserving system integrity.

## Language

**Main Executable**:
The root Mach-O executable specified by `CFBundleExecutable` in the application bundle's `Contents/Info.plist`.
_Avoid_: Entry binary, root process

**Helper Bundle**:
An auxiliary macOS application bundle embedded in `Contents/Frameworks/` or `Contents/MacOS/` responsible for Chromium/Electron multi-process tasks (GPU, Renderer, Utility, Network Service).
_Avoid_: Sub-process, child binary, worker app

**Nested Sub-App**:
A self-contained mini-application bundled inside the parent application's directory hierarchy (e.g. `Contents/MacOS/QQEXGuild.app`).
_Avoid_: Inner app, embedded app

**Process Aliasing**:
The mechanism of renaming the Mach-O binary file on disk so that kernel process accounting (`proc_pidpath`, `ps`, Activity Monitor) matches the clone's distinct name for network proxy and firewall rules.
_Avoid_: Process spoofing, binary renaming
