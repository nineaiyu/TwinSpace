[中文版](Readme_zh.md)  [English](Readme.md) | 🌐 **[Online Docs](https://nineaiyu.github.io/TwinSpace)** | 📖 **[User Guide (EN)](https://nineaiyu.github.io/TwinSpace/en/)** | **[用户使用手册 (中文)](https://nineaiyu.github.io/TwinSpace/zh/)**

# TwinSpace — macOS App Multi-Instancing & Isolated Environments

[![Tests](https://github.com/nineaiyu/TwinSpace/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/nineaiyu/TwinSpace/actions/workflows/test.yml)

> 🚀 **TwinSpace** is a macOS app multi-instancing and isolated environment manager. It groups clones of Chrome, ZCode, WorkBuddy, CodeBuddy, Qoder, Trae and other apps into independent spaces with separate data, Keychain namespaces, browser profiles and OAuth handlers. It also supports per-clone HTTP / SOCKS5 proxies, automated recipe matching, ad-hoc re-signing and sandbox removal — with a native GUI, a scriptable CLI, and in-app auto-updates.
>
> 📖 **Looking for a beginner-friendly tutorial?** Visit our online documentation at **[nineaiyu.github.io/TwinSpace](https://nineaiyu.github.io/TwinSpace)**, or check out the **[English User Manual](https://nineaiyu.github.io/TwinSpace/en/)** | **[中文使用手册](https://nineaiyu.github.io/TwinSpace/zh/)**.

---

## 📥 Download

Visit the [GitHub Releases](https://github.com/nineaiyu/TwinSpace/releases) page to download the latest release of TwinSpace.

TwinSpace provides two distribution packages with **identical core functionality**:

| Distribution Package | Target Audience | Description |
| :--- | :--- | :--- |
| **`TwinSpace-{version}-arm64.dmg`** | 👶 **General Users (Strongly Recommended)** | macOS Native GUI desktop application installer (`.dmg`). Provides a modern, visual card-based interface with zero terminal knowledge required. |
| **`TwinSpaceCli.tar.gz`** | ⚡ **Power Users / Developers** | Standalone binary command-line tool archive (`TwinSpaceCli`). Zero Python dependencies required; ideal for terminal power users, automation scripts, and CI/CD pipelines. |

> 💡 **User Guidance**:
> - **Beginners / Everyday Users**: Please **prioritize downloading and using the GUI app (`.dmg`)**. It offers an intuitive visual interface for one-click cloning, app launching, status monitoring, and settings — and checks for updates right inside the app (⚙️ Settings → 🔄 Check for Updates), so future upgrades are one click away.
> - **Advanced Users / Developers**: Use the **CLI tool (`TwinSpaceCli` / `twinspace`)** for fast terminal interaction, batch scripting, deep application probing, and headless workflows.

---

## ✨ Key Features

- 📦 **Dual-Engine Cloning Mechanism**:
  - **Hard Clone**: Designed for native and social applications (WeChat, QQ, Telegram, AI clients, Chrome, Edge, Arc, etc.). Duplicates the entire App Bundle, modifies `Info.plist` and Bundle Identifier, injects isolated `HOME` / `TMPDIR` data directories via in-process dynamic library injection (`libtwinspace_env.dylib`) or Mach-O binary launcher hijack, optionally strips App Sandbox restrictions, and performs ad-hoc code re-signing.
  - **Soft Clone**: Designed for modern code editors and browsers (Cursor, VS Code, Firefox, Brave, Tor, Zed, etc.). Generates a lightweight wrapper bundle, automatically injecting isolated `--user-data-dir` / `--profile` launch arguments and proxy environment variables.
- 🗂 **Isolated Multi-App Environments**: Create one environment per account (`phone1`, `phone2`, ...). Every app in the environment shares the environment's Chrome profile and data root while keeping its own HOME, userData, Keychain namespace and OAuth handler. Clone names default to `App-Environment` and can be customized per app.
- 🔍 **Intelligent App Prober**: Automatically inspects Mach-O architectures, frameworks, and code signing sandbox entitlements for any application without a pre-configured recipe, dynamically determining the optimal soft/hard clone strategy and generating recommended recipes.
- 🌐 **Isolated Network Proxies**: Configure dedicated HTTP or SOCKS5 proxies (with authentication support) per cloned application without interfering with host system or primary application traffic.
- 📑 **Recipe Engine**: 39 built-in recipes for popular apps and AI Agent tools, with local override support via `~/TwinSpace/recipes/`.
- 🪄 **Interactive Wizard**: Step-by-step interactive CLI guide supporting terminal drag-and-drop application paths, automatic name incrementing, custom data directory configuration, and on-the-fly proxy setup.
- 🔄 **Lifecycle Management**: View cloned apps (`list`), re-clone after primary app updates while preserving user and chat data (`update`), and safely remove clones with interactive prompts or flag controls (`remove` with `--with-data` / `--keep-data`).
- 🛡️ **Security & Privilege Elevation**: Writing to `~/TwinSpace/Apps` requires no admin privileges; writing to `/Applications` uses native single-prompt macOS `osascript` authorization; robust path escaping via `shlex.quote` throughout.
- 🔄 **In-App Auto-Update**: The GUI checks GitHub Releases for new versions, verifies the SHA-256 checksum, and swaps in the new `TwinSpace.app` — no manual re-download.
- 🌙 **Bilingual, Theme-Aware UI**: English and 简体中文 with live switching, plus automatic Light/Dark mode following the system appearance.


---

## 🗂 Isolated Multi-App Environments

An environment is a named group of app clones plus one Chrome profile. Apps in
`phone1` only open `phone1`'s browser; data, Keychain entries and OAuth callbacks
do not leak into `phone2` or the original apps.

```bash
# Create a phone-sized environment; every installed supported app is used by default.
twinspace env create phone1

# Or pick a built-in template / explicit apps and custom clone names.
twinspace env create phone1 --template phone
twinspace env create phone1 --apps chrome,zcode,workbuddy \
  --clone-name zcode=ZCode-work --clone-name workbuddy=WorkBuddy-work

twinspace env list
twinspace env open phone1
twinspace env update phone1          # rebuild all apps after source upgrades
twinspace env backup phone1          # archive every app's data
twinspace env restore phone1 ~/TwinSpace/Backups/phone1-*.tar.gz

# Share a portable template or import it on another Mac.
twinspace env export phone1 -o phone1.yaml
twinspace env import phone1.yaml --name phone2
```

#### Browser binding & external browsers

By default an environment clones Chrome along with the other apps, and every
non-Chrome app is pinned to that clone: links, OAuth callbacks and logins open
in the environment's own browser with the environment's profile
(`~/TwinSpace/Data/Environments/<name>/Browser`).

To use an **external browser** instead:

```bash
# Links open in Microsoft Edge, but with an isolated profile kept inside the
# environment (the browser binary itself is not cloned or modified).
twinspace env create phone1 --apps zcode,workbuddy \
  --browser "/Applications/Microsoft Edge.app"

# No --browser and no Chrome in the app list: links simply open in the macOS
# default browser (no binding, no hijack).
twinspace env create phone1 --apps zcode

# Advanced per-app overrides (repeatable). Example: point one app at an
# existing browser profile instead of the environment-owned one.
twinspace env create phone1 --apps zcode \
  --set-env zcode=TWINSPACE_BROWSER_DATA_DIR="$HOME/Library/Application Support/Google/Chrome"
```

Notes:
- The binding is stored per app and survives `env update` and `env export`/`import`.
- Link hijacking requires a **hard clone** (isolation hook); apps whose recipe
  uses soft clone cannot bind a browser.
- Browser-binding variables (set automatically, or via `--set-env`):

| Variable | Meaning |
| :--- | :--- |
| `TWINSPACE_BROWSER_APP_PATH` | Browser `.app` that receives http/HTTPS links opened by this clone |
| `TWINSPACE_BROWSER_DATA_DIR` | Profile directory passed as `--user-data-dir` (must be set for hijacking to engage) |
| `TWINSPACE_BROWSER_FALLBACK_APP_PATH` | Fallback browser when `APP_PATH` is missing (default: system Chrome) |
| `TWINSPACE_BROWSER_EXTRA_ARGS` | Extra Chromium-style launch arguments for the hijacked browser |
| `TWINSPACE_KEYCHAIN_PREFIX` | Keychain service namespace prefix isolating this clone's passwords |
| `TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES` | Keychain services excluded from the namespace |
| `TWINSPACE_DEVICE_UUID` | Per-environment value returned for IOKit `IOPlatformUUID` |
| `TWINSPACE_DEVICE_SERIAL` | Per-environment value returned for IOKit `IOPlatformSerialNumber` |
| `TWINSPACE_DEVICE_SEED` | Per-environment seed used to derive disk UUIDs and interface MAC addresses |
| `TWINSPACE_DEVICE_HOSTNAME` | Per-environment hostname returned by `gethostname` |
| `TWINSPACE_OAUTH_SCHEMES` | OAuth/URL schemes pinned to the bound browser |
| `TWINSPACE_SCHEME_ALLOW_REGISTRATION` | Allow the clone to register URL scheme handlers |
| `TWINSPACE_COCOA_HOME_HOOK` | Enable the Cocoa HOME redirection hook |
| `TWINSPACE_DATA_DIR` / `TWINSPACE_ENV_DIR` | Recipe placeholders for the isolated data roots |

#### Using an environment browser from the host

The environment's Chrome clone (`~/TwinSpace/Apps/Chrome-<env>.app`) is a
standalone signed app — the host can use it directly:

- **Launch it like any app**: Finder double-click, Spotlight, Dock, or
  `open -a "Chrome-<env>"`. It always opens with the environment's isolated
  profile (that account's logins), separate from your daily browser.
- **Open host links in it**: right-click a link and choose *Open With*, use
  `open -na "Chrome-<env>" --args <url>`, or set it as the macOS **default
  browser** in System Settings → Desktop & Dock. Browser clones keep their URL
  scheme registration, so they appear in the default-browser list alongside
  the original.
- `twinspace env open <env> --apps chrome` launches it from the CLI.
- The binding survives `env update`: the clone keeps its bundle id and path,
  so a default-browser choice does not need to be redone.

Built-in templates: `all`, `phone` (Chrome + ZCode + WorkBuddy + CodeBuddy) and
`dev` (Chrome + CodeBuddy + Qoder + Trae). The GUI exposes the same workflows in
**My Environments** (`+ New Environment`, `Update All`, `Backup`), and every app
row has its own **Open / Close** button next to `Open All`.

Users upgrading from ATBClone can keep their existing data root with:

```bash
twinspace migrate                 # ~/TwinSpace -> ~/ATBClone compatibility symlink
twinspace migrate --move          # physical move + state path rewrite (advanced)
```

---

## 🖥️ Graphical User Interface (GUI — Recommended for General Users)

> 💡 **Tip for Everyday Users**: If you prefer not to use the terminal, download `TwinSpace-{version}-arm64.dmg` from [GitHub Releases](https://github.com/nineaiyu/TwinSpace/releases), open the DMG, drag `TwinSpace.app` to your `Applications` folder, and launch it directly.

The native macOS desktop interface provides a visual, streamlined experience:

1. **Isolated Environments**:
   - Create one environment per account and add Chrome, ZCode, WorkBuddy, CodeBuddy, Qoder or Trae.
   - Open, update or back up the whole environment from one card; clone names are editable per app.
   - First launch lands directly on this page when no clones or environments exist yet.
2. **Dashboard & Clone Cards**:
   - Dual view (list / card grid) with search, strategy filters and sorting; the grid adapts its column count to the window width.
   - **Double-click a row to launch** the clone; update after primary app upgrades (preserving chat history and data) or remove clones — delete actions are red-highlighted and always ask for confirmation.
3. **Visual Clone Creation**:
   - Drag and drop or browse for any `.app` bundle from your system.
   - Automatically matches built-in recipes or runs the App Prober on unlisted applications.
   - Customize clone name, display title, custom icon, dedicated data directory (e.g. on external SSDs), and independent HTTP / SOCKS5 proxies.
4. **Built-in Recipe Library**:
   - Explore 39 pre-configured application recipes (WeChat, QQ, Chrome, Cursor, ChatGPT, Claude, etc.) categorized by type, complete with sandbox stripping rules and isolation strategies.
5. **App Prober (Deep Architecture Inspection)**:
   - Inspect any unknown macOS app's Mach-O architecture, frameworks, and sandbox entitlements, and generate custom recipe YAML files with one click.
6. **System Diagnostics (Doctor)**:
   - Self-check system prerequisites, Xcode command-line tools, codesigning utilities, and storage permissions to ensure optimal stability.
7. **Bilingual UI, Dark Mode & System Tray**:
   - English and 简体中文 with live switching; Light/Dark appearance follows the system; optional menu-bar tray with minimize-to-tray.
8. **In-App Updates**:
   - One-click update check from the sidebar or Settings; packages are checksum-verified before install.

*(For developers running the GUI from source: run `bash scripts/run_gui.sh` or `python -m twinspace.gui`)*

---

## 🚀 Command Line Interface (CLI — For Power Users & Scripting)

> ⚡ **For Advanced Users & Automation**: The CLI tool (`twinspace` or standalone binary `TwinSpaceCli`) provides full control over the cloning engine with scriptable commands, rich terminal tables, and automation support.

### 1. Interactive Wizard (CLI Guided Mode)

No need to memorize CLI options—follow the interactive prompts in your terminal:
```bash
twinspace wizard
```
*Workflow: Drag and drop `.app` path ➔ Auto-match recipe ➔ Set clone name ➔ Set display name and icon ➔ Select destination directory ➔ Custom data directory (if supported) ➔ Optional proxy setup ➔ Confirm and create.*

---

### 2. Command Line Quick Clone (`clone`)

#### Basic Clone (Auto-incremented name, defaults to `~/TwinSpace/Apps`)
```bash
twinspace clone /Applications/WeChat.app
```

#### Specify Clone Name and Output Directory
```bash
twinspace clone /Applications/WeChat.app --name "WeChat-Work" --output-dir ~/TwinSpace/Apps
```

#### Custom Data Storage Directory (`--data-dir`)
For applications that support data isolation (Chromium series, Firefox, WeChat, etc.), you can specify a custom data storage directory (e.g. on an external SSD or dedicated workspace):
```bash
twinspace clone /Applications/Chrome.app --name "Chrome-Custom" --data-dir /Volumes/ExternalSSD/ChromeData
```
*Note: The prober automatically detects if the application supports data isolation; attempting to set `--data-dir` on unsupported applications (e.g. Zed) will fail with a friendly error.*


#### Clone Applications without Pre-configured Recipes (Auto-triggers Prober)
When cloning an app without a built-in recipe, TwinSpace automatically runs App Prober to inspect the architecture and sandbox entitlements, dynamically generates the optimal recipe, and executes the clone:
```bash
twinspace clone /Applications/Example.app --name "Example-Work"
```

#### Configure Dedicated Network Proxies (HTTP / SOCKS5)
```bash
# Configure HTTP proxy with credentials (passwords stored securely in macOS Keychain)
twinspace clone /Applications/Telegram.app \
  --name "Telegram-Proxy" \
  --proxy-host 127.0.0.1 \
  --proxy-port 7890 \
  --proxy-type http \
  --proxy-user alice \
  --proxy-password "my_secret_token"

# Configure SOCKS5 proxy
twinspace clone /Applications/ChatGPT.app \
  --name "ChatGPT-US" \
  --proxy-host 127.0.0.1 \
  --proxy-port 1080 \
  --proxy-type socks5
```

#### Injection Strategy Selection (`--injection-strategy`)
For Hard Clone apps, customize how isolated environment variables (`HOME`, `TMPDIR`, proxies) are injected into the cloned application:
```bash
# Auto mode (default): probes Mach-O load command headroom, prefers in-process dylib injection, falls back to launcher if headroom < 56 bytes
twinspace clone /Applications/WeChat.app --injection-strategy auto

# Force dylib injection (guarantees native macOS system notifications and Menu Bar status icons)
twinspace clone /Applications/WeChat.app --injection-strategy dylib

# Force Mach-O binary launcher hijack
twinspace clone /Applications/Chrome.app --injection-strategy launcher
```
*Options:* `auto` (default/recommended), `dylib` (in-process dynamic library, Darwin PIDVersion preserved), `launcher` (C binary launcher hijack).

---

### 3. List Cloned Applications (`list`)

View all clones managed by TwinSpace in a Rich-formatted table:
```bash
twinspace list
```
Example output:
```
┏━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 名称     ┃ 原 APP  ┃ Bundle ID            ┃ 策略       ┃ 创建时间         ┃ 代理                   ┃
┡━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 微信2    │ 微信    │ com.tencent.xinWeChat │ hard_clone │ 2026-08-18 22:30 │ 未开启                 │
│ TG-Proxy │ Telegram│ ru.keepcoder.Telegram │ hard_clone │ 2026-08-18 22:45 │ http://127.0.0.1:7890  │
│ Chrome2  │ Chrome  │ com.google.Chrome    │ hard_clone │ 2026-08-18 23:00 │ 未开启                 │
└──────────┴─────────┴━━━━━━━━━━━━━━━━━━━━━━┴━━━━━━━━━━━━┴━━━━━━━━━━━━━━━━━━┴━━━━━━━━━━━━━━━━━━━━━━━━┘
```

---

### 4. Synchronize Clones After Primary App Updates (`update`)

When the primary application is updated via the Mac App Store or website, update your clone with a single command while **preserving all chat history, logins, and data**:
```bash
twinspace update WeChat2
```

---

### 5. Remove Clones (`remove`)

#### Interactive Removal (Recommended)
When executing remove in an interactive terminal, TwinSpace prompts whether to also delete the data directory:
```bash
twinspace remove WeChat2
# Interactive prompt: Also delete data directory /Users/.../TwinSpace/Data/WeChat2? [y/N]
```

#### Explicitly Remove Application and Data Directory (`--with-data`)
```bash
twinspace remove WeChat2 --with-data
```

#### Explicitly Remove Application Only and Keep Data (`--keep-data`)
```bash
twinspace remove WeChat2 --keep-data
```
*Note: If the application or data directory is located in a root/admin path (e.g. `/Applications`), privilege escalation will be requested automatically once to clean up safely.*


---

### 6. Recipe Management & Custom Extensions (`recipe`)

#### List All Built-in Recipes
```bash
twinspace recipe list
```

#### View Recipe Details for a Specific Bundle ID
```bash
twinspace recipe show com.tencent.xinWeChat
```

#### Custom & Override Recipes
Place a custom YAML recipe in `~/TwinSpace/recipes/<bundle_id>.yaml` to automatically take precedence:
```yaml
# Example: ~/TwinSpace/recipes/com.example.customapp.yaml
bundle_id: com.example.customapp
app_name: CustomApp
strategy: hard_clone
app_type: cocoa # Options: cocoa, electron, chromium, firefox, generic
strip_sandbox: false # false (recommended): utilizes macOS native container isolation; true: strips App Sandbox
environment_injection:
  HOME: '{{TWINSPACE_DATA_DIR}}/Home'
  TMPDIR: '{{TWINSPACE_DATA_DIR}}/Tmp'
proxy:
  enabled: true
  type: http
  host: 127.0.0.1
  port: 7890
```

---

### 7. Deep Application Probing & Recipe Generation (`probe`)

Perform deep architecture and code signing inspection on any local `.app` bundle, analyze its engine (Chromium / Electron / Gecko / Native) and sandbox status, and output a recommended TwinSpace Recipe YAML:

#### Basic Probing with Terminal Summary
```bash
twinspace probe /Applications/Example.app
```

#### Probe and Save Directly to Local Repository (`~/TwinSpace/recipes/<bundle_id>.yaml`)
```bash
twinspace probe /Applications/Example.app --save
```

#### Export Generated Recipe to a Specific Path
```bash
twinspace probe /Applications/Example.app -o /path/to/recipe.yaml
```

#### Output in Machine-Readable JSON
```bash
twinspace probe /Applications/Example.app --json
```

---

### 8. View Version & System Information (`version`)

```bash
# View detailed system and runtime environment information
twinspace version

# Output version number only
twinspace version --short
# or
twinspace --version
```

---

### 9. Isolated Environments (`env`)

```bash
twinspace env list
twinspace env create phone1 --template phone
twinspace env create phone1 --apps chrome,zcode --clone-name zcode=ZCode-work
twinspace env open phone1
twinspace env update phone1
twinspace env backup phone1
twinspace env restore phone1 <archive>
twinspace env export phone1 -o phone1.yaml
twinspace env import phone1.yaml --name phone2
twinspace env templates
twinspace migrate
```

---

## 📋 Built-in Recipes

| Category | Application | Bundle Identifier | Strategy | App Type | Strip Sandbox |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Category | Application | Bundle Identifier | Strategy | App Type | Strip Sandbox |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Instant Messaging & Collaboration** | WeChat | `com.tencent.xinWeChat` | Hard Clone | `cocoa` | ✔ |
|  | WeCom (企业微信) | `com.tencent.WeWorkMac` | Hard Clone | `chromium` | ✔ |
|  | QQ | `com.tencent.qq` | Hard Clone | `electron` | ✔ |
|  | Lark (飞书) | `com.electron.lark` | Hard Clone | `electron` | ✔ |
|  | Telegram | `ru.keepcoder.Telegram` | Hard Clone | `cocoa` | ✔ |
|  | Telegram Desktop | `org.telegram.desktop` | Hard Clone | `generic` | ✔ |
|  | LINE | `jp.naver.line.mac` | Hard Clone | `cocoa` | ✔ |
|  | KakaoTalk | `com.kakao.KakaoTalkMac` | Hard Clone | `cocoa` | ✔ |
|  | Slack | `com.tinyspeck.slackmacgap` | Hard Clone | `electron` | ✔ |
|  | Discord | `com.hnc.Discord` | Hard Clone | `electron` | ✔ |
|  | Skype | `com.skype.skype` | Hard Clone | `electron` | ✔ |
| **AI Clients & Agent Tools** | Claude | `com.anthropic.claudefordesktop` | Hard Clone | `electron` | ✔ |
|  | ChatGPT | `com.openai.codex` | Hard Clone | `electron` | ✔ |
|  | ChatGPT | `com.openai.chat` | Hard Clone | `electron` | ✔ |
|  | Gemini | `com.google.GeminiMacOS` | Hard Clone | `cocoa` | ✔ |
|  | Antigravity | `com.google.antigravity` | Hard Clone | `electron` | ✔ |
|  | Antigravity IDE | `com.google.antigravity-ide` | Hard Clone | `electron` | ✔ |
| **Isolated Environment Suite** | ZCode | `dev.zcode.app` | Hard Clone | `electron` | — |
|  | WorkBuddy | `com.tencent.workbuddy.mac` | Hard Clone | `electron` | — |
|  | WorkBuddy AI (intl, opt-in) | `com.workbuddy.workbuddy-ai` | Hard Clone | `electron` | — |
|  | CodeBuddy CN | `com.tencent.codebuddycn` | Hard Clone | `electron` | — |
|  | CodeBuddy AI (intl, opt-in) | `com.tencent.codebuddy` | Hard Clone | `electron` | — |
|  | Qoder CN | `com.qodercn.app` | Hard Clone | `electron` | — |
|  | Trae CN | `cn.trae.app` | Hard Clone | `electron` | — |
| **Browsers** | Google Chrome | `com.google.Chrome` | Soft Clone | `chromium` | — |
|  | Microsoft Edge | `com.microsoft.edgemac` | Hard Clone | `chromium` | — |
|  | Brave Browser | `com.brave.Browser` | Soft Clone | `chromium` | — |
|  | Firefox | `org.mozilla.firefox` | Soft Clone | `firefox` | — |
|  | Tor Browser | `org.torproject.torbrowser` | Soft Clone | `firefox` | — |
|  | Arc | `company.thebrowser.Browser` | Hard Clone | `chromium` | — |
| **Media & Entertainment** | Bilibili (哔哩哔哩) | `com.bilibili.bilibiliPC` | Hard Clone | `electron` | ✔ |
|  | Douyin (抖音) | `com.bytedance.douyin.desktop` | Hard Clone | `electron` | ✔ |
|  | Netease Music (网易云音乐) | `com.netease.163music` | Hard Clone | `chromium` | ✔ |
|  | Steam | `com.valvesoftware.steam` | Hard Clone | `cocoa` | ✔ |
| **Productivity & Utilities** | WPS Office | `com.kingsoft.wpsoffice.mac` | Hard Clone | `cocoa` | ✔ |
|  | JianYing Pro (剪映专业版) | `com.lemon.lvpro` | Hard Clone | `chromium` | ✔ |
|  | CapCut | `com.lemon.lvoverseas` | Hard Clone | `chromium` | ✔ |
| **Developer Tools** | Cursor | `com.todesktop.230313mzl4w4u92` | Soft Clone | `electron` | — |
|  | VS Code | `com.microsoft.VSCode` | Soft Clone | `electron` | — |
|  | Android Studio | `com.google.android.studio` | Hard Clone | `generic` | ✔ |
|  | Zed | `dev.zed.Zed` | Soft Clone | `generic` | — |

**KakaoTalk validation:** Concurrent launch with the original app and notifications have been checked. Clone login, separate-account data isolation, and login persistence after restarting the clone have not yet been verified.

---

## 🔐 Security & Privacy Notes

- **Input hardening**: every value that reaches a shell command, PlistBuddy invocation or generated launcher (clone names, bundle IDs, display names, proxy settings) is validated centrally in `twinspace/validation.py`; shell paths are escaped with `shlex.quote`.
- **Deletion guards**: `remove` / `update` refuse to touch system paths (`/System`, `/Library`, your home directory itself, etc.), require an `.app` target, and run the actual `rm -rf` through `shlex.quote`.
- **Secrets**: proxy passwords are stored in the macOS Keychain (service `twinspace.proxy`), never in `clones.yaml`; state files are written atomically with `0600` permissions.
- **Signing**: clones are re-signed ad-hoc (`codesign --sign -`). TwinSpace does not modify or bypass Gatekeeper for the original apps, and sandbox stripping only applies when a recipe explicitly opts in.
- **Telemetry**: none. Update checks only contact `github.com` for `latest.json`.

## 🛠️ Prerequisites & Development Setup

- **Operating System**: macOS 13.0 or later on Apple Silicon (arm64). Release packages are built for arm64 only.
- **Python**: Python 3.12+ (strictly required for `build_cli.sh` compilation)
- **System Tools**: Xcode Command Line Tools installed (provides `codesign`, `xcode-select`, `PlistBuddy`)

```bash
# 1. Install Xcode Command Line Tools (if not already installed)
xcode-select --install

# 2. Create a virtualenv and install in development mode (with the GUI stack)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"

# 3. Run environment self-check
twinspace doctor
```

---

## 🏷️ Semantic Version Management

The project adheres to semantic versioning `x.y.z` (see `pyproject.toml` for the current version) and provides a dedicated version management script at `scripts/manage_version.py`:

```bash
# 1. Check version consistency across configuration files
python scripts/manage_version.py --show

# 2. Bump semantic version (patch: 1.0.0 -> 1.0.1, minor: 1.0.0 -> 1.1.0, major: 1.0.0 -> 2.0.0)
python scripts/manage_version.py --bump patch
python scripts/manage_version.py --bump minor
python scripts/manage_version.py --bump major

# 3. Set an explicit version
python scripts/manage_version.py 1.0.0

# 4. Preview changes without writing to disk
python scripts/manage_version.py --bump patch --dry-run
```

*The script automatically updates version declarations in `pyproject.toml`, `src/twinspace/__init__.py`, and other configuration files.*

---

## 🏗️ Standalone Binary Packaging (Build)

The project includes automated build scripts to package both the CLI and GUI into standalone binaries:

```bash
# 1. Build CLI standalone binary (dist/TwinSpaceCli)
bash scripts/build_cli.sh

# 2. Build GUI DMG installer (dist/TwinSpace-<version>-arm64.dmg)
bash scripts/build_gui.sh
```

The resulting standalone binary will be generated under `dist/`:
```bash
# Verify the built binary
./dist/TwinSpaceCli --help
./dist/TwinSpaceCli version
./dist/TwinSpaceCli doctor
./dist/TwinSpaceCli probe /Applications/Example.app
```

---

## 🧪 Running Tests

This project follows TDD and automated test verification practices, with full unit and integration test suites:

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

---

## 📂 Directory & Storage Architecture

```
~/TwinSpace/
├── config.yaml           # User configuration & preferences (language, tray, etc.)
├── clones.yaml           # Global clone state tracking registry
├── recipes/              # User custom recipe directory (optional overrides)
└── Data/                 # Isolated data directories per clone
    ├── WeChat2/
    │   ├── Home/         # Isolated user home directory
    │   └── Tmp/          # Isolated temporary directory
    └── Chrome2/          # Isolated Chrome User Data directory
```

```
src/twinspace/
├── cli/                  # CLI command layer (Click + Rich)
│   ├── cmd_clone.py      # Main clone command (supports auto-probing)
│   ├── cmd_doctor.py     # Environment checks
│   ├── cmd_env.py        # Environment management (create/list/update/backup/import/export)
│   ├── cmd_list.py       # Clone listing
│   ├── cmd_probe.py      # Deep app architecture probing & recipe generation
│   ├── cmd_migrate.py    # Legacy ATBClone data migration
│   ├── cmd_recipe.py     # Recipe management
│   ├── cmd_remove.py     # Clone removal
│   ├── cmd_update.py     # Clone update & sync
│   ├── cmd_version.py    # Version & system information
│   └── cmd_wizard.py     # Interactive wizard
├── core/                 # Core domain models & cloning engines
│   ├── cloning/          # Shared clone lifecycle manager (CLI + GUI)
│   ├── environments/     # Environment manager, portable specs, templates, backups
│   ├── app_inspector.py  # App metadata inspection & auto-numbering
│   ├── app_prober.py     # Deep probing, sandbox inspection & recipe extraction
│   ├── clone_task.py     # Clone task entity
│   ├── engines.py        # Soft & Hard cloning execution engines
│   ├── models.py         # Domain models
│   └── state.py          # YAML state management
├── gui/                  # Native macOS GUI desktop application layer (Toga / Briefcase)
│   ├── components/       # Reusable UI widgets (cards, sidebar, top bar)
│   ├── services/         # GUI service bridge (clone, doctor, probe, recipe, tray)
│   └── views/            # GUI views (dashboard, recipes, probe, doctor, settings, logs)
├── executor/             # Low-level executors (Subprocess / AppleScript elevation)
│   └── runner.py
└── recipes/              # Recipe models, loaders & 39 built-in rules
    ├── builtin/          # Built-in YAML recipes
    ├── loader.py         # Recipe matching & priority loader
    └── models.py         # Pydantic validation models
```

## 📖 User Manual & Documentation

For a comprehensive walkthrough of TwinSpace GUI, custom recipes, engine mechanics, and troubleshooting, visit the online documentation at **[nineaiyu.github.io/TwinSpace](https://nineaiyu.github.io/TwinSpace)**:

- 🇺🇸 **[English User Guide (nineaiyu.github.io/TwinSpace/en/)](https://nineaiyu.github.io/TwinSpace/en/)**
  - [Chapter 1: Basic Operations & Clone Management](https://nineaiyu.github.io/TwinSpace/en/01-basic-operations/)
  - [Chapter 2: Custom Recipes for Niche Apps](https://nineaiyu.github.io/TwinSpace/en/02-advanced-custom-recipes/)
  - [Chapter 3: Under the Hood & Advanced Parameters](https://nineaiyu.github.io/TwinSpace/en/03-under-the-hood-and-internals/)
  - [Chapter 4: FAQ & Diagnostic Troubleshooting](https://nineaiyu.github.io/TwinSpace/en/04-faq-and-troubleshooting/)
- 🇨🇳 **[简体中文用户使用手册 (nineaiyu.github.io/TwinSpace/zh/)](https://nineaiyu.github.io/TwinSpace/zh/)**
  - [第一章：基础操作与分身管理](https://nineaiyu.github.io/TwinSpace/zh/01-basic-operations/)
  - [第二章：冷门应用规则定制与基础参数详解](https://nineaiyu.github.io/TwinSpace/zh/02-advanced-custom-recipes/)
  - [第三章：实现原理解析与高级参数全解](https://nineaiyu.github.io/TwinSpace/zh/03-under-the-hood-and-internals/)
  - [第四章：常见问题 (FAQ)、系统体检与反馈](https://nineaiyu.github.io/TwinSpace/zh/04-faq-and-troubleshooting/)

---

## 📄 License & Release Notes

- **Documentation**: [Online Docs](https://nineaiyu.github.io/TwinSpace) | [English Guide](https://nineaiyu.github.io/TwinSpace/en/) | [中文手册](https://nineaiyu.github.io/TwinSpace/zh/)
- **License**: GPL-3.0-or-later. TwinSpace is a rebranded distribution of ATBClone; see [ATTRIBUTION.md](ATTRIBUTION.md).
- **Release Notes**: [English](docs/release/ReleaseNote.md) | [简体中文](docs/release/ReleaseNote_zh.md)

