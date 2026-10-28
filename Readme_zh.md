[中文版](Readme_zh.md)  [English](Readme.md) | 🌐 **[在线文档](https://nineaiyu.github.io/TwinSpace)** | 📖 **[用户使用手册 (中文)](https://nineaiyu.github.io/TwinSpace/zh/)** | **[User Guide (EN)](https://nineaiyu.github.io/TwinSpace/en/)**

# TwinSpace — macOS 应用多开与隔离环境管理器

[![Tests](https://github.com/nineaiyu/TwinSpace/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/nineaiyu/TwinSpace/actions/workflows/test.yml)

> 🚀 **TwinSpace** 是一个专为 macOS 设计的应用多开与隔离环境管理器。可以把 Chrome、ZCode、WorkBuddy、CodeBuddy、Qoder、Trae 等应用的多个分身按账号划分到独立环境，每个环境拥有独立数据、Keychain 命名空间、浏览器 Profile 与 OAuth 回调；同时支持独立网络代理（HTTP / SOCKS5）、规则匹配、重签名与沙盒解除——提供原生图形界面与可脚本化 CLI，并内置应用内自动更新。
>
> 📖 **新手小白入门指引？** 请访问官方在线使用手册：**[nineaiyu.github.io/TwinSpace](https://nineaiyu.github.io/TwinSpace)**，或查阅 **[TwinSpace 中文使用手册](https://nineaiyu.github.io/TwinSpace/zh/)** | **[English Manual](https://nineaiyu.github.io/TwinSpace/en/)**。

---

## 📥 软件下载 (Download)

请前往 [GitHub Releases](https://github.com/nineaiyu/TwinSpace/releases) 页面下载最新版本的 TwinSpace。

Release 页面主要提供两个发布文件，**核心功能完全一致**：

| 发布包 | 适用人群 | 说明 |
| :--- | :--- | :--- |
| **`TwinSpace-<version>-arm64.dmg`** | 👶 **普通用户 / 小白用户（强烈推荐）** | macOS 原生 GUI 桌面客户端安装包 (`.dmg`)。提供现代化卡片式图形界面，零终端操作门槛，开箱即用。 |
| **`TwinSpaceCli.tar.gz`** | ⚡ **专业用户 / 开发者** | 独立二进制命令行工具归档（`TwinSpaceCli`）。无需安装 Python 环境，专为终端极客、脚本自动化与高级运维场景打造。 |

> 💡 **使用建议与指引**：
> - **普通用户 / 小白用户**：请**优先下载并使用 GUI 图形界面版 (`.dmg`)**。图形化操作简单直观，支持卡片化浏览、一键克隆、状态查看、快捷启动与偏好设置。
> - **专业用户 / 开发者**：推荐使用 **CLI 命令行工具 (`TwinSpaceCli` / `twinspace`)**，支持丰富的子命令、深度架构探测、批量脚本与灵活参数调优。

---

## ✨ 核心特性

- 📦 **双引擎克隆架构 (Dual-Engine Cloning Mechanism)**：
  - **硬克隆 (Hard Clone)**：面向原生/社交与独立架构应用（微信、QQ、Telegram、AI 客户端、Chrome、Edge、Arc 等）。完整复制 App Bundle，修改 `Info.plist` 与 Bundle Identifier，通过进程内动态库注入 (`libtwinspace_env.dylib`) 或 Mach-O 二进制启动器拦截注入独立 `HOME` / `TMPDIR` 数据目录，支持按需剥离 App Sandbox 沙盒限制，并完成 Ad-hoc 重新签名。
  - **软克隆 (Soft Clone)**：面向现代代码编辑器与浏览器（Cursor、VS Code、Firefox、Brave、Tor、Zed 等）。生成轻量级启动器包装（Wrapper Bundle），自动注入 `--user-data-dir` / `--profile` 参数与独立代理环境变量。
- 🗂 **多 App 隔离环境**：按账号创建 `phone1`、`phone2` 等环境，把 Chrome、ZCode、WorkBuddy、CodeBuddy、Qoder、Trae 组合进同一环境。环境内应用共用独立 Chrome Profile 和数据根，同时各自保留独立的 HOME、userData、Keychain 命名空间和 OAuth 回调。分身名默认是 `应用名-环境名`，也可以逐个修改。
- 🔍 **智能应用探测 (App Prober)**：遇到未预设规则的任意 macOS 应用程序时，自动分析其 Mach-O 架构、Frameworks 与代码签名沙盒权限，动态决定软/硬克隆策略并提取推荐规则。
- 🌐 **独立网络代理 (Isolated Network Proxies)**：为每个分身实例配置独立的 HTTP 或 SOCKS5 代理（支持认证），与系统主网络及母体应用互不干扰。
- 📑 **规则引擎 (Recipe Engine)**：内置 39 条常用应用与 AI Agent 工具分身规则，支持通过 `~/TwinSpace/recipes/` 本地优先级覆盖自定义规则。
- 🪄 **交互式向导 (Interactive Wizard)**：全流程引导式 CLI，支持终端拖拽 `.app` 路径、自动命名递增、自定义数据目录与快捷代理配置。
- 🔄 **生命周期管理**：查看已有分身（`list`）、主应用升级后一键重克隆并保留用户数据（`update`）、安全删除分身（`remove` 支持 `--with-data` / `--keep-data` 与交互确认）。
- 🛡️ **安全与提权机制**：默认克隆至 `~/TwinSpace/Apps` 无需 root/sudo 权限；如需写入系统级 `/Applications` 采用原生单次 `osascript` 授权提权；严格使用 `shlex.quote` 保证路径转义安全。
- 🔄 **应用内自动更新**：图形界面一键检查 GitHub Releases 新版本，SHA-256 校验通过后自动换装新版 `TwinSpace.app`，无需手动重新下载。
- 🌙 **中英双语 · 深色跟随**：界面支持简体中文/英文实时切换，深浅色外观自动跟随系统。


---

## 🗂 多 App 隔离环境

环境是一组应用分身加一个独立 Chrome Profile。`phone1` 里的应用只会打开
`phone1` 的浏览器，数据、Keychain 和 OAuth 回调不会串到 `phone2` 或原应用。

```bash
# 创建环境；默认使用本机已安装的全部支持应用
twinspace env create phone1

# 使用内置模板、显式应用列表和自定义分身名
twinspace env create phone1 --template phone
twinspace env create phone1 --apps chrome,zcode,workbuddy \
  --clone-name zcode=ZCode-work --clone-name workbuddy=WorkBuddy-work

twinspace env list
twinspace env open phone1
twinspace env update phone1          # 原应用升级后批量重建
twinspace env backup phone1          # 备份环境内全部 App 数据
twinspace env restore phone1 ~/TwinSpace/Backups/phone1-*.tar.gz

# 导出可移植模板，在另一台 Mac 导入
twinspace env export phone1 -o phone1.yaml
twinspace env import phone1.yaml --name phone2
```

#### 浏览器绑定与外部浏览器

默认情况下，环境会随其他应用一起克隆 Chrome，且所有非 Chrome 应用都会绑定到
这个分身：链接、OAuth 回调与登录都会打开环境自己的浏览器，并使用环境专属的
Profile（`~/TwinSpace/Data/Environments/<名称>/Browser`）。

如需在环境中使用**外部浏览器**：

```bash
# 链接用 Microsoft Edge 打开，但使用环境内隔离的 Profile
# （不会克隆、也不会改动 Edge 本体）
twinspace env create phone1 --apps zcode,workbuddy \
  --browser "/Applications/Microsoft Edge.app"

# 不带 --browser 且应用列表不含 Chrome：链接直接走 macOS 系统默认浏览器
# （不绑定、不劫持）
twinspace env create phone1 --apps zcode

# 高级用法：按应用覆盖（可重复）。例如让某个应用复用已有的浏览器 Profile：
twinspace env create phone1 --apps zcode \
  --set-env zcode=TWINSPACE_BROWSER_DATA_DIR="$HOME/Library/Application Support/Google/Chrome"
```

说明：
- 绑定按应用持久化保存，`env update` 与 `env export`/`import` 后依然生效。
- 链接劫持依赖**硬克隆**（隔离钩子）；规则为软克隆的应用无法绑定浏览器。
- 浏览器绑定相关变量（自动注入，也可用 `--set-env` 手动指定）：

| 环境变量 | 作用 |
| :--- | :--- |
| `TWINSPACE_BROWSER_APP_PATH` | 接管本分身 http/HTTPS 链接的浏览器 `.app` 路径 |
| `TWINSPACE_BROWSER_DATA_DIR` | 传给浏览器的 `--user-data-dir` Profile 目录（必须设置，劫持才会生效） |
| `TWINSPACE_BROWSER_FALLBACK_APP_PATH` | `APP_PATH` 不可用时的回退浏览器（默认系统 Chrome） |
| `TWINSPACE_BROWSER_EXTRA_ARGS` | 劫持启动时附加的 Chromium 风格启动参数 |
| `TWINSPACE_KEYCHAIN_PREFIX` | 本分身钥匙串服务的命名空间前缀 |
| `TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES` | 不参与命名空间隔离的钥匙串服务 |
| `TWINSPACE_DEVICE_UUID` | 本环境通过 IOKit 返回的 `IOPlatformUUID` |
| `TWINSPACE_DEVICE_SERIAL` | 本环境通过 IOKit 返回的 `IOPlatformSerialNumber` |
| `TWINSPACE_DEVICE_SEED` | 派生磁盘 UUID 与网卡 MAC 的环境种子 |
| `TWINSPACE_DEVICE_HOSTNAME` | 本环境 `gethostname` 返回的主机名 |
| `TWINSPACE_OAUTH_SCHEMES` | 固定绑定到环境浏览器的 OAuth/URL scheme |
| `TWINSPACE_SCHEME_ALLOW_REGISTRATION` | 允许分身注册 URL scheme 处理器 |
| `TWINSPACE_COCOA_HOME_HOOK` | 启用 Cocoa 层 HOME 重定向钩子 |
| `TWINSPACE_DATA_DIR` / `TWINSPACE_ENV_DIR` | 规则模板中的隔离数据根占位符 |

#### 在宿主机上使用环境里的浏览器

环境的 Chrome 分身（`~/TwinSpace/Apps/Chrome-<环境名>.app`）本身就是一个
独立签名的应用，宿主机可以直接使用：

- **像普通应用一样启动**：访达双击、Spotlight、Dock，或
  `open -a "Chrome-<环境名>"`。它始终使用环境内的隔离 Profile（该账号的
  登录态），与日常浏览器互不干扰。
- **让宿主机的链接用它打开**：右键链接选择“打开方式”，使用
  `open -na "Chrome-<环境名>" --args <网址>`，或在
  系统设置 → 桌面与程序坞 中把它设为**默认浏览器**。浏览器分身保留了
  URL scheme 注册，会与原 Chrome 一起出现在默认浏览器候选列表中。
- CLI 可用 `twinspace env open <环境名> --apps chrome` 启动。
- 绑定在 `env update` 后依然有效：分身的 Bundle ID 与路径不变，
  默认浏览器选择无需重设。

内置模板：`all`、`phone`（Chrome + ZCode + WorkBuddy + CodeBuddy）、
`dev`（Chrome + CodeBuddy + Qoder + Trae）。GUI 的「我的环境」提供
「新建环境」「全部更新」「备份数据」入口。

从 ATBClone 升级的用户可以保留原数据目录：

```bash
twinspace migrate                 # 创建 ~/TwinSpace -> ~/ATBClone 兼容软链
twinspace migrate --move          # 物理移动并改写状态路径（高级）
```

---

## 🖥️ 图形化界面使用指南 (GUI — 推荐普通用户使用)

> 💡 **新手与普通用户提示**：如果您不习惯终端命令行操作，请直接从 [GitHub Releases](https://github.com/nineaiyu/TwinSpace/releases) 下载 `TwinSpace-<version>-arm64.dmg` 安装包，将 `TwinSpace.app` 拖入 `应用程序` 文件夹即可直接运行使用！后续升级无需重新下载——应用内（⚙️ 全局设置 → 🔄 检查更新）即可一键升级。

macOS 原生桌面图形客户端提供直观、全功能的应用分身管理：

1. **隔离环境 (My Environments)**：
   - 按账号创建环境，把 Chrome、ZCode、WorkBuddy、CodeBuddy、Qoder、Trae 加进同一环境。
   - 在环境卡片上直接全部打开、批量更新或备份数据；每个 App 一行，可单独打开/关闭。
   - 每个 App 的分身名可单独修改。
   - 首次使用（尚无分身与环境）时自动引导到本页面。
2. **仪表盘与分身卡片 (Dashboard)**：
   - 列表/卡片双视图，支持搜索、策略筛选与排序；卡片网格列数随窗口宽度自适应。
   - **双击列表行直接启动分身**；原应用升级后一键同步（完整保留聊天记录与登录数据）；删除操作红色标识并始终二次确认。
3. **可视化新建分身向导**：
   - 支持拖拽或文件选择器选取任意 `.app` 应用本体。
   - 自动匹配内置规则或动态触发深度架构探测。
   - 可视化自定义分身名称、显示标题、独立数据目录（如外接移动硬盘）以及 HTTP/SOCKS5 专属代理配置。
4. **内置规则库 (Recipe Library)**：
   - 分类浏览内置的 39 条热门应用规则（微信、QQ、Chrome、Cursor、ChatGPT、Claude 等），查看沙盒剥离与隔离策略。
5. **应用深度探测器 (App Prober)**：
   - 可视化检测任意未知应用的 Mach-O 架构、Frameworks 与沙盒权限，一键生成专属分身规则。
6. **系统健康自检 (Doctor)**：
   - 一键自检系统版本、Xcode 命令行工具、代码签名环境与存储权限，保障分身稳定运行。
7. **中英双语 · 深色模式 · 菜单栏托盘**：
   - 简体中文/English 实时切换，深浅色跟随系统，支持最小化至 macOS 菜单栏托盘常驻。
8. **应用内更新**：
   - 侧栏或全局设置一键检查更新，安装包经校验和验证后自动换装。

*(开发者如需从源码启动 GUI：运行 `bash scripts/run_gui.sh` 或 `python -m twinspace.gui`)*

---

## 🚀 命令行工具使用指南 (CLI — 专业用户 / 脚本自动化)

> ⚡ **专业用户与自动化场景**：CLI 工具（`twinspace` 或独立二进制 `TwinSpaceCli`）提供完整的终端控制能力，支持丰富的子命令与漂亮的 Rich 终端输出，适合极客与脚本集成。

### 1. 交互式向导（CLI 引导模式）

无需记忆参数，根据终端提示一步步操作：
```bash
twinspace wizard
```
*流程包括：拖入 `.app` 路径 ➔ 自动匹配分身规则 ➔ 设置分身名称 ➔ 设置显示名称与图标 ➔ 选择输出路径 ➔ 自定义数据目录（若支持） ➔ 可选配置代理 ➔ 确认生成。*

---

### 2. 命令行快速克隆 (`clone`)

#### 基础克隆（自动递增编号，默认输出至 `~/TwinSpace/Apps`）
```bash
twinspace clone /Applications/WeChat.app
```

#### 指定分身名称与输出目录
```bash
twinspace clone /Applications/WeChat.app --name "微信工作版" --output-dir ~/TwinSpace/Apps
```

#### 自定义数据存储目录 (`--data-dir`)
对于支持数据隔离的应用（如 Chromium 系列、Firefox、微信等），可指定自定义数据存储路径（例如放置于外部 SSD 或专属工作区）：
```bash
twinspace clone /Applications/Chrome.app --name "Chrome-Custom" --data-dir /Volumes/ExternalSSD/ChromeData
```
*注：系统会自动探测应用是否支持数据隔离；若目标应用无数据隔离规则（如 Zed），将自动拦截并提示错误。*

#### 未预设规则应用克隆（自动触发深度探测）
克隆未内置规则的应用时，TwinSpace 会自动触发 App Prober 探测架构与沙盒权限，动态生成最佳规则后执行克隆：
```bash
twinspace clone /Applications/Example.app --name "Example-Work"
```

#### 为分身配置专属独立网络代理 (HTTP / SOCKS5)
```bash
# 配置 HTTP 代理并指定账号密码（密码安全保存至 macOS 系统钥匙串）
twinspace clone /Applications/Telegram.app \
  --name "Telegram-Proxy" \
  --proxy-host 127.0.0.1 \
  --proxy-port 7890 \
  --proxy-type http \
  --proxy-user alice \
  --proxy-password "my_secret_token"

# 配置 SOCKS5 代理
twinspace clone /Applications/ChatGPT.app \
  --name "ChatGPT-US" \
  --proxy-host 127.0.0.1 \
  --proxy-port 1080 \
  --proxy-type socks5
```

#### 选择环境变量注入策略 (`--injection-strategy`)
对于硬克隆应用，可控制隔离环境变量（`HOME`/`TMPDIR`/代理等）如何注入到目标进程中：
```bash
# 自动模式（默认）：静态探测 Mach-O Load Command 剩余空间，首选进程内 dylib 注入，空间不足 56 字节时安全降级为 launcher
twinspace clone /Applications/WeChat.app --injection-strategy auto

# 强制 dylib 注入（保证 macOS 系统原生通知和菜单栏状态栏图标完整可用）
twinspace clone /Applications/WeChat.app --injection-strategy dylib

# 强制 Mach-O 二进制启动器拦截
twinspace clone /Applications/Chrome.app --injection-strategy launcher
```
*可选策略：* `auto`（默认/推荐）、`dylib`（进程内动态库注入，保持 Darwin PIDVersion 纯净）、`launcher`（C 二进制启动器拦截）。

---

### 3. 查看分身列表 (`list`)

通过漂亮的 Rich 表格查看所有由 TwinSpace 管理的分身状态：
```bash
twinspace list
```
输出示例：
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

### 4. 更新原应用后的分身同步 (`update`)

当 App Store 或官网更新了主应用版本时，一键更新分身，**保留所有聊天记录与登录状态（数据目录不丢失）**：
```bash
twinspace update 微信2
```

---

### 5. 删除分身 (`remove`)

#### 交互式删除（推荐）
在终端中直接执行删除时，系统会交互式询问是否同时清理数据目录：
```bash
twinspace remove 微信2
# 交互提示：是否同时删除数据目录 /Users/.../TwinSpace/Data/微信2？[y/N]
```

#### 显式同时删除分身应用及数据目录 (`--with-data`)
```bash
twinspace remove 微信2 --with-data
```

#### 显式仅删除应用本体并保留数据 (`--keep-data`)
```bash
twinspace remove 微信2 --keep-data
```
*注：若分身应用或数据目录位于需要管理员权限的系统目录（如 `/Applications`），系统会自动通过一次提权安全清理。*


---

### 6. 分身规则管理与自定义扩展 (`recipe`)

#### 列出所有内置应用分身规则
```bash
twinspace recipe list
```

#### 查看特定应用的分身规则 YAML
```bash
twinspace recipe show com.tencent.xinWeChat
```

#### 自定义与覆盖分身规则
在 `~/TwinSpace/recipes/<bundle_id>.yaml` 放置 YAML 规则文件即可自动优先加载覆盖：
```yaml
# 示例：~/TwinSpace/recipes/com.example.customapp.yaml
bundle_id: com.example.customapp
app_name: CustomApp
strategy: hard_clone
app_type: cocoa # 可选类型：cocoa, electron, chromium, firefox, generic
strip_sandbox: false # false (推荐): 依托 macOS 原生容器沙盒隔离；true: 强制剥离沙盒
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

### 7. 深度应用探测与分身规则生成 (`probe`)

对任意本地 `.app` 进行深度架构与代码签名权限探测，分析其运行内核（Chromium / Electron / Gecko / Native）、沙盒状态，并输出推荐的 TwinSpace Recipe YAML：

#### 基础探测与终端展示
```bash
twinspace probe /Applications/Example.app
```

#### 探测并直接保存至本地规则库 (`~/TwinSpace/recipes/<bundle_id>.yaml`)
```bash
twinspace probe /Applications/Example.app --save
```

#### 导出分身规则到指定文件
```bash
twinspace probe /Applications/Example.app -o /path/to/recipe.yaml
```

#### 机器可读 JSON 输出
```bash
twinspace probe /Applications/Example.app --json
```

---

### 8. 查看版本与系统信息 (`version`)

```bash
# 查看详细系统与运行环境信息
twinspace version

# 仅输出版本号
twinspace version --short
# 或
twinspace --version
```

---

### 9. 隔离环境管理 (`env`)

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

## 📋 内置分身规则 (Built-in Recipes)

| 类别 | 应用名称 | Bundle Identifier | 克隆策略 | 应用类型 (App Type) | 沙盒解除 (Strip Sandbox) |
| :--- | :--- | :--- | :--- | :--- | :---: |
| 类别 | 应用名称 | Bundle Identifier | 克隆策略 | 应用类型 (App Type) | 沙盒解除 (Strip Sandbox) |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **即时通讯 & 协同办公** | 微信 (WeChat) | `com.tencent.xinWeChat` | 硬克隆 | `cocoa` | ✔ |
|  | 企业微信 (WeCom) | `com.tencent.WeWorkMac` | 硬克隆 | `chromium` | ✔ |
|  | QQ | `com.tencent.qq` | 硬克隆 | `electron` | ✔ |
|  | 飞书 (Lark) | `com.electron.lark` | 硬克隆 | `electron` | ✔ |
|  | Telegram | `ru.keepcoder.Telegram` | 硬克隆 | `cocoa` | ✔ |
|  | Telegram Desktop | `org.telegram.desktop` | 硬克隆 | `generic` | ✔ |
|  | LINE | `jp.naver.line.mac` | 硬克隆 | `cocoa` | ✔ |
|  | KakaoTalk | `com.kakao.KakaoTalkMac` | 硬克隆 | `cocoa` | ✔ |
|  | Slack | `com.tinyspeck.slackmacgap` | 硬克隆 | `electron` | ✔ |
|  | Discord | `com.hnc.Discord` | 硬克隆 | `electron` | ✔ |
|  | Skype | `com.skype.skype` | 硬克隆 | `electron` | ✔ |
| **AI 客户端 & Agent 工具** | Claude | `com.anthropic.claudefordesktop` | 硬克隆 | `electron` | ✔ |
|  | ChatGPT | `com.openai.codex` | 硬克隆 | `electron` | ✔ |
|  | ChatGPT | `com.openai.chat` | 硬克隆 | `electron` | ✔ |
|  | Gemini | `com.google.GeminiMacOS` | 硬克隆 | `cocoa` | ✔ |
|  | Antigravity | `com.google.antigravity` | 硬克隆 | `electron` | ✔ |
|  | Antigravity IDE | `com.google.antigravity-ide` | 硬克隆 | `electron` | ✔ |
| **隔离环境套件** | ZCode | `dev.zcode.app` | 硬克隆 | `electron` | — |
|  | WorkBuddy | `com.tencent.workbuddy.mac` | 硬克隆 | `electron` | — |
|  | WorkBuddy AI（国际版，需手动勾选） | `com.workbuddy.workbuddy-ai` | 硬克隆 | `electron` | — |
|  | CodeBuddy CN | `com.tencent.codebuddycn` | 硬克隆 | `electron` | — |
|  | CodeBuddy AI（国际版，需手动勾选） | `com.tencent.codebuddy` | 硬克隆 | `electron` | — |
|  | Qoder CN | `com.qodercn.app` | 硬克隆 | `electron` | — |
|  | Trae CN | `cn.trae.app` | 硬克隆 | `electron` | — |
| **浏览器** | Chrome | `com.google.Chrome` | 软克隆 | `chromium` | — |
|  | Edge | `com.microsoft.edgemac` | 硬克隆 | `chromium` | — |
|  | Brave Browser | `com.brave.Browser` | 软克隆 | `chromium` | — |
|  | Firefox | `org.mozilla.firefox` | 软克隆 | `firefox` | — |
|  | Tor Browser | `org.torproject.torbrowser` | 软克隆 | `firefox` | — |
|  | Arc | `company.thebrowser.Browser` | 硬克隆 | `chromium` | — |
| **媒体 & 娱乐** | 哔哩哔哩 (Bilibili) | `com.bilibili.bilibiliPC` | 硬克隆 | `electron` | ✔ |
|  | 抖音 (Douyin) | `com.bytedance.douyin.desktop` | 硬克隆 | `electron` | ✔ |
|  | 网易云音乐 (Netease Music) | `com.netease.163music` | 硬克隆 | `chromium` | ✔ |
|  | Steam | `com.valvesoftware.steam` | 硬克隆 | `cocoa` | ✔ |
| **办公 & 效率** | WPS Office | `com.kingsoft.wpsoffice.mac` | 硬克隆 | `cocoa` | ✔ |
|  | 剪映专业版 (JianYing Pro) | `com.lemon.lvpro` | 硬克隆 | `chromium` | ✔ |
|  | CapCut | `com.lemon.lvoverseas` | 硬克隆 | `chromium` | ✔ |
| **开发者工具** | Cursor | `com.todesktop.230313mzl4w4u92` | 软克隆 | `electron` | — |
|  | VS Code | `com.microsoft.VSCode` | 软克隆 | `electron` | — |
|  | Android Studio | `com.google.android.studio` | 硬克隆 | `generic` | ✔ |
|  | Zed | `dev.zed.Zed` | 软克隆 | `generic` | — |

**KakaoTalk 验证范围：** 已验证与原应用同时运行及通知功能。分身登录、不同账号之间的数据隔离，以及重启分身后保持登录状态尚未验证。

---

## 🔐 安全与隐私说明

- **输入加固**：所有会进入 shell 命令、PlistBuddy 或生成启动器的值（分身名、Bundle ID、显示名、代理配置）都在 `twinspace/validation.py` 集中校验；shell 路径统一经 `shlex.quote` 转义。
- **删除防护**：`remove` / `update` 拒绝操作系统路径（`/System`、`/Library`、用户主目录本身等），要求目标以 `.app` 结尾，`rm -rf` 前强制路径校验与转义。
- **密钥安全**：代理密码保存在 macOS 钥匙串（service `twinspace.proxy`），绝不写入 `clones.yaml`；状态文件以 `0600` 权限原子写入。
- **签名策略**：分身使用 ad-hoc 重签名（`codesign --sign -`）；TwinSpace 不绕过原应用的 Gatekeeper 校验，沙盒解除仅在规则显式开启时生效。
- **无遥测**：不采集任何数据；更新检查仅访问 `github.com` 获取 `latest.json`。

## 🛠️ 开发与环境依赖 (Development Setup)

- **操作系统**：macOS 13.0 及以上，Apple Silicon (arm64)。发布产物目前仅提供 arm64 架构。
- **Python**：Python 3.12+（`build_cli.sh` 编译时强制要求）
- **系统开发工具**：已安装 Xcode Command Line Tools（提供 `codesign`, `xcode-select`, `PlistBuddy`）

```bash
# 1. 安装 Xcode Command Line Tools (若尚未安装)
xcode-select --install

# 2. 创建虚拟环境并以可编辑模式安装全部依赖 (含 GUI)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"

# 3. 运行环境自检
twinspace doctor
```

---

## 🏷️ 语义化版本管理 (Version Management)

项目采用标准的语义化版本号格式 `x.y.z`（当前版本以 `pyproject.toml` 为准），并提供了专用的版本管理脚本 `scripts/manage_version.py`：

```bash
# 1. 检查各配置文件版本是否一致
python scripts/manage_version.py --show

# 2. 语义化升级版本 (patch: 1.0.0 -> 1.0.1, minor: 1.0.0 -> 1.1.0, major: 1.0.0 -> 2.0.0)
python scripts/manage_version.py --bump patch
python scripts/manage_version.py --bump minor
python scripts/manage_version.py --bump major

# 3. 指定显式版本
python scripts/manage_version.py 1.0.0

# 4. 预览变更（不实际写入文件）
python scripts/manage_version.py --bump patch --dry-run
```

*脚本会自动同步更新 `pyproject.toml`、`src/twinspace/__init__.py` 等目标文件的版本定义。*

---

## 🏗️ 独立二进制构建与打包 (Build)

项目提供了自动化构建与打包脚本，支持独立 CLI 二进制及 GUI DMG 安装包构建：

```bash
# 1. 构建 CLI 独立二进制 (生成于 dist/TwinSpaceCli)
bash scripts/build_cli.sh

# 2. 构建 GUI 原生安装包 (生成于 dist/TwinSpace-<version>-arm64.dmg)
bash scripts/build_gui.sh
```

构建完成后将在 `dist/` 目录生成产物：
```bash
# 验证 CLI 独立二进制
./dist/TwinSpaceCli --help
./dist/TwinSpaceCli version
./dist/TwinSpaceCli doctor
./dist/TwinSpaceCli probe /Applications/Example.app
```

---

## 🧪 运行测试

本项目严格遵循 TDD 与自动化验证规范，包含完整的单元测试与集成测试：

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

---

## 📂 目录与数据存储架构

```
~/TwinSpace/
├── config.yaml           # 用户配置与偏好设置 (语言、托盘等)
├── clones.yaml           # 全局分身状态追踪记录
├── recipes/              # 用户自定义分身规则存放目录 (可选覆盖)
└── Data/                 # 各分身独立的数据隔离目录
    ├── 微信2/
    │   ├── Home/         # 隔离的独立用户主目录
    │   └── Tmp/          # 隔离的临时目录
    └── Chrome2/          # Chrome 独立 User Data 目录
```

```
src/twinspace/
├── cli/                  # CLI 命令行层 (Click + Rich)
│   ├── cmd_clone.py      # 克隆主命令 (支持未配置规则自动探测)
│   ├── cmd_doctor.py     # 环境检测
│   ├── cmd_env.py        # 环境管理（创建/列表/更新/备份/导入导出）
│   ├── cmd_list.py       # 分身列表
│   ├── cmd_probe.py      # 应用深度架构探测与规则生成
│   ├── cmd_migrate.py    # 旧 ATBClone 数据迁移
│   ├── cmd_recipe.py     # 分身规则管理
│   ├── cmd_remove.py     # 分身删除
│   ├── cmd_update.py     # 分身更新
│   ├── cmd_version.py    # 版本与系统信息展示
│   └── cmd_wizard.py     # 交互式向导
├── core/                 # 核心领域模型与克隆引擎
│   ├── cloning/          # 共享克隆生命周期管理器（CLI + GUI）
│   ├── environments/     # 环境管理、可移植配置、模板与备份
│   ├── app_inspector.py  # App 元数据检查与自动编号
│   ├── app_prober.py     # 深度架构探测、沙盒检查与动态规则生成
│   ├── clone_task.py     # 克隆任务实体
│   ├── engines.py        # Soft & Hard 克隆执行引擎
│   ├── models.py         # 基础模型
│   └── state.py          # YAML 状态管理
├── gui/                  # 原生 macOS GUI 桌面客户端层 (Toga / Briefcase)
│   ├── components/       # 可复用 UI 组件 (分身卡片、侧边栏、顶部栏)
│   ├── services/         # GUI 业务服务桥接 (clone, doctor, probe, recipe, tray)
│   └── views/            # GUI 视图 (仪表盘、规则库、探测器、自检、设置、日志)
├── executor/             # 底层执行器 (Direct Subprocess / AppleScript 提权)
│   └── runner.py
└── recipes/              # 规则模型、加载器与 39 个内置规则
    ├── builtin/          # 内置 YAML 规则
    ├── loader.py         # 规则匹配与优先级加载
    └── models.py         # Pydantic 校验模型
```

## 📖 用户使用手册 (User Guide)

如需查阅小白入门图文教程、规则定制指南、底层原理解析与常见问题解答，请访问官方在线手册 **[nineaiyu.github.io/TwinSpace](https://nineaiyu.github.io/TwinSpace)**：

- 🇨🇳 **[简体中文用户使用手册 (nineaiyu.github.io/TwinSpace/zh/)](https://nineaiyu.github.io/TwinSpace/zh/)**
  - [第一章：基础操作与分身管理](https://nineaiyu.github.io/TwinSpace/zh/01-basic-operations/)（7 步向导、无损更新、批量操作、安全删除）
  - [第二章：冷门应用规则定制与基础参数详解](https://nineaiyu.github.io/TwinSpace/zh/02-advanced-custom-recipes/)（智能探针 Prober、规则编辑器、基础参数）
  - [第三章：实现原理解析与高级参数全解](https://nineaiyu.github.io/TwinSpace/zh/03-under-the-hood-and-internals/)（软硬分身机制、壳劫持、高级参数与路径宏）
  - [第四章：常见问题 (FAQ)、系统体检与反馈](https://nineaiyu.github.io/TwinSpace/zh/04-faq-and-troubleshooting/)（数据安全、防封号原理解析、Doctor 体检、GitHub 提报指引）
- 🇺🇸 **[English User Guide (nineaiyu.github.io/TwinSpace/en/)](https://nineaiyu.github.io/TwinSpace/en/)**
  - [Chapter 1: Basic Operations & Clone Management](https://nineaiyu.github.io/TwinSpace/en/01-basic-operations/)
  - [Chapter 2: Custom Recipes for Niche Apps](https://nineaiyu.github.io/TwinSpace/en/02-advanced-custom-recipes/)
  - [Chapter 3: Under the Hood & Advanced Parameters](https://nineaiyu.github.io/TwinSpace/en/03-under-the-hood-and-internals/)
  - [Chapter 4: FAQ & Diagnostic Troubleshooting](https://nineaiyu.github.io/TwinSpace/en/04-faq-and-troubleshooting/)

---

## 📄 License 与 Release Notes

- **使用手册 (Guide)**: [在线文档](https://nineaiyu.github.io/TwinSpace) | [简体中文手册](https://nineaiyu.github.io/TwinSpace/zh/) | [English Guide](https://nineaiyu.github.io/TwinSpace/en/)
- **开源协议**: GPL-3.0-or-later。TwinSpace 是基于 ATBClone 的改名发行版，详见 [ATTRIBUTION.md](ATTRIBUTION.md)。
- **更新日志 (Release Notes)**: [English](docs/release/ReleaseNote.md) | [简体中文](docs/release/ReleaseNote_zh.md)

