# 多账号多环境隔离改造说明

本文对应这次源码改造：在一台 Mac 上为多个手机号分别建立
`ZCode + WorkBuddy + CodeBuddy + Qoder + Trae + Chrome` 环境，并保证登录态、
数据目录、Keychain、浏览器 Cookie 和 OAuth 回调互不串号。

## 1. 为什么之前的克隆会串号

ZCode 和 WorkBuddy 都是 Electron 应用，但它们不是“标准地只读 `--user-data-dir`”：

- ZCode 在启动时显式调用 `app.setName()`、`app.setPath("userData"/"sessionData")`，并自己维护 `~/.zcode`。仅传 `--user-data-dir` 会被它覆盖。
- WorkBuddy 在启动时显式设置 `WORKBUDDY_CONFIG_DIR`、`app.setPath("userData"/"sessionData")`；账号凭据写在共享的 `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`。
- Qoder 没有走标准的 `--user-data-dir`，而是把真实 userData 固定到
  `~/Library/Application Support/com.qodercn.app.stable`，必须同时重定向 Cocoa 的
  `NSHomeDirectory` / `NSSearchPathForDirectoriesInDomains` 才能隔离。
- CodeBuddy / Trae 是 VS Code 系 Electron 应用：支持
  `--user-data-dir`、`--extensions-dir`、`--disable-updates`，但 userData 路径会优先被
  `VSCODE_PORTABLE` / `VSCODE_APPDATA` 覆盖；克隆启动时会主动清掉这些继承变量。
- 旧版软克隆直接 `exec` 原应用二进制，进程的 Bundle ID、签名和 Keychain 身份仍然是原应用。
- 旧版偏好种子逻辑会无条件把真实的 `~/Library/Keychains` 软链进克隆 Home。
- ZCode 的 OAuth 回调固定为 `zcode://oauth/callback`，多个克隆都声明同一个 scheme，启动时会互相抢占。

所以只“多开一个窗口”不够，必须同时处理 **数据根、应用身份、Keychain、浏览器、URL scheme** 五层。

## 2. 改造后的隔离模型

每个环境使用一个目录：

```text
~/TwinSpace/
  Apps/
    ZCode-phone1.app
    WorkBuddy-phone1.app
    CodeBuddy-phone1.app
    Qoder-phone1.app
    Trae-phone1.app
    Chrome-phone1.app
  Data/
    Environments/
      phone1/
        Browser/                 # 环境专用 Chrome profile
        ZCode-phone1/
          Home/ UserData/ Session/ Tmp/
        WorkBuddy-phone1/
          Config/ Home/ Tmp/
        CodeBuddy-phone1/
          Home/ UserData/ Extensions/ Config/ Tmp/
        Qoder-phone1/
          Home/ Config/ CLI/ Logs/ Tmp/
        Trae-phone1/
          Home/ UserData/ Extensions/ Tmp/
```

### 2.1 数据目录

ZCode 内置 recipe 注入：

```yaml
HOME: '{{TWINSPACE_DATA_DIR}}/Home'
TMPDIR: '{{TWINSPACE_DATA_DIR}}/Tmp/'
ZCODE_DESKTOP_APPLICATION_NAME: '{{TWINSPACE_CLONE_NAME}}'
ZCODE_DESKTOP_HOME_DIR: '{{TWINSPACE_DATA_DIR}}/Home'
ZCODE_DESKTOP_USER_DATA_DIR: '{{TWINSPACE_DATA_DIR}}/UserData'
ZCODE_DESKTOP_SESSION_DATA_DIR: '{{TWINSPACE_DATA_DIR}}/Session'
```

WorkBuddy 内置 recipe 注入：

```yaml
HOME: '{{TWINSPACE_DATA_DIR}}/Home'
TMPDIR: '{{TWINSPACE_DATA_DIR}}/Tmp/'
WORKBUDDY_CONFIG_DIR: '{{TWINSPACE_DATA_DIR}}/Config'
CODEBUDDY_CONFIG_DIR: '{{TWINSPACE_DATA_DIR}}/Config'
WORKBUDDY_USER_DATA_DIR: '{{TWINSPACE_DATA_DIR}}/Config/app'
WORKBUDDY_DATA_DIR: '{{TWINSPACE_DATA_DIR}}/Config'
WORKBUDDY_APP_NAME: '{{TWINSPACE_CLONE_NAME}}'
WORKBUDDY_INSTANCE_NUMBER: '{{TWINSPACE_INSTANCE_NUMBER}}'
WORKBUDDY_DEEPLINK_SCHEMES: 'workbuddy,workbuddy-{{TWINSPACE_INSTANCE_NUMBER}},buddy-app'
```

CodeBuddy / Trae 使用 VS Code 参数：

```yaml
HOME: '{{TWINSPACE_DATA_DIR}}/Home'
TMPDIR: '{{TWINSPACE_DATA_DIR}}/Tmp/'
launch_args:
  - --user-data-dir={{TWINSPACE_DATA_DIR}}/UserData
  - --extensions-dir={{TWINSPACE_DATA_DIR}}/Extensions
  - --disable-updates
  - --skip-release-notes
```

Qoder 使用自定义 appData，且额外隔离 CLI/SDK 配置：

```yaml
HOME: '{{TWINSPACE_DATA_DIR}}/Home'
TMPDIR: '{{TWINSPACE_DATA_DIR}}/Tmp/'
QODERCN_CONFIG_DIR: '{{TWINSPACE_DATA_DIR}}/Config'
QODERCN_CLI_HOME: '{{TWINSPACE_DATA_DIR}}/CLI'
QODER_LOG_DIR: '{{TWINSPACE_DATA_DIR}}/Logs'
```

`HOME` 会同时影响 Node 的 `os.homedir()`；隔离 dylib 里的 Cocoa HOME hook
会把 `NSHomeDirectory` / `NSSearchPathForDirectoriesInDomains` 也重定向到克隆 Home。
因此 Qoder 的 `~/Library/Application Support/com.qodercn.app.stable`、
WorkBuddy 的共享 auth 文件、各应用的 `~/.trae-cn` / `~/.codebuddycn` / `~/.qoder-cn`
都会落到克隆目录。

### 2.2 Keychain

`libtwinspace_isolation.dylib` 会同时 interpose：

- 现代 API：`SecItemAdd / SecItemCopyMatching / SecItemUpdate / SecItemDelete`
- Legacy API：`SecKeychainFindGenericPassword / SecKeychainAddGenericPassword`

两类 API 都会把 `service` 加上 `TWINSPACE_KEYCHAIN_PREFIX`，例如
`ZCode-phone1 Safe Storage` → `twinspace.<hash>.ZCode-phone1 Safe Storage`。
这样即使应用混用现代/legacy Keychain（WorkBuddy 的 TuringShield 就是 legacy），
每个克隆也会读写自己的 keychain 项，不会访问原始账号的项而触发 ACL 提示。

- 支持 `TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES`，通配符结尾（如 `com.turingshield.*`）表示前缀匹配；
  默认不需要排除。
- 克隆 Home 的 `Library/Keychains` 仍软链到真实钥匙串目录，用于兼容 legacy API 对
  keychain 路径的查找；实际 item 已按 clone 前缀隔离。
- ZCode / WorkBuddy / Trae 的 Cookie 实测是明文本地存储，账号登录文件也在各自数据根内；
  Keychain 钩子主要保护 safeStorage、TuringShield、CLI token 以及未来版本可能新增的凭据。

> 注意：钥匙串 **文件** 仍然是用户级共享的，隔离的是 item 的 service 命名空间。
> 如果要求“连钥匙串文件也彻底隔离”，需要为每个环境使用独立 macOS 用户。

### 2.3 浏览器 / OAuth

隔离 dylib 还做了三件事：

1. swizzle `NSWorkspace` 的 `openURL:` 系列方法。克隆里任何 `http(s)` 打开动作都会改为：
   ```text
   <环境 Chrome 克隆>/Contents/MacOS/Google Chrome \
     --user-data-dir=<环境>/Browser <url>
   ```
   如果 recipe/`--set-env` 指定了 `TWINSPACE_BROWSER_APP_PATH`，会优先使用该 Chrome 克隆；路径不存在时回退到系统 Chrome。Path 中携带的是该环境的 `Browser` profile，因此第一个环境的 ZCode 只会打开第一个环境的 Chrome，不会落到其他环境。
2. 在打开浏览器前，把 `TWINSPACE_OAUTH_SCHEMES` 的默认处理器固定到当前克隆。
   ZCode 使用 `zcode`；CodeBuddy / Qoder / Trae 分别使用
   `codebuddycn` / `qoder-cn` / `trae-cn`。启动时应用自己调用
   `setAsDefaultProtocolClient` 会被拦截，避免多个克隆互相抢占。
3. Cocoa HOME hook 把 `NSHomeDirectory` / `NSSearchPathForDirectoriesInDomains`
   重定向到克隆 Home，用于 Qoder 这类不读取 `--user-data-dir` 的 Electron 应用。

各应用桌面端接收登录结果的通道不同，规则按通道分别处理：

- **ZCode**：浏览器最终回跳 `zcode://oauth/callback`，规则把 `zcode` 固定到当前分身；
  客户端同时保留轮询兜底，即使回调丢失也能完成登录。
- **CodeBuddy / Qoder**：打开登录页后由客户端用 `state` / PKCE `nonce` 轮询服务端换取 token，
  不依赖 URL scheme，因此不存在“回调跳到宿主机”的问题。
- **Trae**：在 `127.0.0.1` 的随机端口起本地 OAuth 服务，`auth_callback_url` 指向该端口，
  回调天然落到发起登录的那个分身。
- **WorkBuddy**：登录 token 同样由客户端轮询完成；但登录页随后会通过
  `/work/launch` 打开 `workbuddy://...` 目标深链（如登录后的目标页）。必须把
  `workbuddy` 固定到当前分身，否则这个跳转会唤醒宿主机原版；同时
  `WORKBUDDY_DEEPLINK_SCHEMES` 必须保留 `workbuddy`，分身才会在 `open-url`
  中接受该深链。

它们的外部浏览器页面都会进入本环境的 Chrome profile。

### 2.4 自动更新

克隆的 recipe 把更新源指向本机不可达地址：

- `ZCODE_UPDATE_FEED_URL=http://127.0.0.1:47999/twinspace-disabled`
- `WORKBUDDY_UPDATE_URL=http://127.0.0.1:47999/twinspace-disabled`

CodeBuddy / Trae 通过 `--disable-updates` 关闭内置更新。
Qoder 目前没有公开的禁用更新环境变量，建议在 Qoder 设置里关闭自动更新；
即使它自行升级，也可以重新执行 `twinspace update` 恢复克隆隔离。

需要升级时，先退出克隆，再更新 `/Applications` 里的原应用，最后执行
`twinspace update <clone>`。更新命令会检测克隆是否仍在运行，运行中会拒绝更新。

### 2.5 硬件设备标识（可选）

部分应用会把账号状态、试用或签到额度绑定到硬件标识上，例如通过 IOKit 读取
`IOPlatformUUID` / `IOPlatformSerialNumber`。这些值在真实机器上所有克隆完全相同。
内置的 ZCode / WorkBuddy / CodeBuddy / Qoder / Trae 规则默认开启隔离，自定义规则
可以按下面的方式显式开启：

```yaml
environment_injection:
  TWINSPACE_DEVICE_UUID: '{{TWINSPACE_DEVICE_UUID}}'
  TWINSPACE_DEVICE_SERIAL: '{{TWINSPACE_DEVICE_SERIAL}}'
  TWINSPACE_DEVICE_SEED: '{{TWINSPACE_DEVICE_SEED}}'
  TWINSPACE_DEVICE_HOSTNAME: '{{TWINSPACE_DEVICE_HOSTNAME}}'
```

隔离 dylib 会 interpose `IORegistryEntryCreateCFProperty` /
`IORegistryEntrySearchCFProperty`，把这两个 key 替换为当前环境的确定性取值。
取值按**环境**派生（同一环境内的所有 App 共享同一套硬件身份，符合“一台机器跑多个
App”的实际情况；无环境的独立分身按分身名派生），`update` 后保持不变。内置的
ZCode / WorkBuddy / CodeBuddy / Qoder / Trae 规则已启用，其他应用可以用
`--set-env` 按需开启。

同一套规则还覆盖：

| 变量 | 拦截点 | 效果 |
| :--- | :--- | :--- |
| `TWINSPACE_DEVICE_SEED` | `DADiskCopyDescription` | 磁盘 media/volume UUID、device GUID 按 `seed + 原值` 派生 |
| `TWINSPACE_DEVICE_SEED` | `getifaddrs` | 每个网卡的 MAC 按 `seed + 网卡名 + 原 MAC` 派生，保留本地管理位 |
| `TWINSPACE_DEVICE_HOSTNAME` | `gethostname` | 返回环境专属主机名 |

派生都以原值为输入，因此多块磁盘、多个网卡之间仍然彼此不同；同一个环境
重启、更新后取值保持不变。

仍无法隔离的硬件/系统信息（进程外或系统级）：

- `ioreg`、`diskutil`、`system_profiler` 等**子进程**输出的硬件信息
- `hw.model`、CPU 型号、内存大小（伪造会影响 Chromium/图形栈的硬件探测，因此不处理）
- 出口 IP（需要给每个分身单独配代理）、已安装应用列表、字体、输入法、显示器信息

## 3. 创建 5 个环境

### 方式 A：GUI（推荐）

打开新版 TwinSpace：

1. 左侧点击 **「🗂 我的环境」**
2. 右上角点击 **「+ 新建环境」**
3. 输入环境名，例如 `phone1`
4. 勾选本环境要安装的 App（Chrome、ZCode、WorkBuddy、CodeBuddy、Qoder、Trae）
5. 按需修改每个 App 右侧的分身名称，默认是 `应用名-环境名`（如 `ZCode-phone1`）
6. 点击 **「创建环境」**

分身名称会用于 `.app` 文件名、应用显示名、Bundle ID 和该 App 的数据目录。默认后缀与环境名一致，
也可以为每个 App 单独修改，例如 `ZCode-work`、`Chrome-acct1`；留空、包含 `/` 或 `\`、或与已有克隆
重名的名称会被拒绝。环境卡片会以 `App · 分身名` 的形式展示实际名称。

创建过程中会显示每个 App 的进度。完成后回到「我的环境」页面，可以：

- **全部打开**：一次启动该环境的 Chrome 和全部 App
- **单个打开/关闭**：每个 App 一行，右侧按钮只启动或退出这一个 App
- **添加 App**：向已有环境补充缺失的 App
- **全部更新**：原应用升级后批量重建环境内的 App
- **备份数据**：把环境内全部 App 的数据归档到 `~/TwinSpace/Backups`
- **删除环境**：可同时删除该环境的数据

> 注意：`/Applications` 里的旧版 TwinSpace 不包含此功能。请运行本仓库构建出的新版本，
> 或用 `bash scripts/run_gui.sh` 从源码启动。

### 方式 B：CLI（适合自动化）

```bash
# 创建环境；默认使用本机已安装的全部支持应用
twinspace env create phone1

# 内置模板：all / phone / dev
twinspace env create phone1 --template phone

# 显式选择 App 并自定义分身名
twinspace env create phone1 --apps chrome,zcode,workbuddy \
  --clone-name zcode=ZCode-work --clone-name workbuddy=WorkBuddy-work

twinspace env list
twinspace env open phone1
twinspace env update phone1
twinspace env backup phone1
twinspace env restore phone1 ~/TwinSpace/Backups/phone1-*.tar.gz
twinspace env export phone1 -o phone1.yaml
twinspace env import phone1.yaml --name phone2
twinspace env templates
```

### 方式 C：一键脚本

```bash
cd /path/to/TwinSpace
bash scripts/setup_environments.sh phone1 phone2 phone3 phone4 phone5
```

脚本会为每个名字创建：

- `Chrome-<name>.app`，数据目录固定为 `~/TwinSpace/Data/Environments/<name>/Browser`
- `ZCode-<name>.app`
- `WorkBuddy-<name>.app`
- `CodeBuddy-<name>.app`
- `Qoder-<name>.app`
- `Trae-<name>.app`

每个 App 克隆的 `TWINSPACE_BROWSER_APP_PATH` 都会指向同名 Chrome 克隆，因此同一环境里的
所有程序共用该环境的 Chrome profile，跨环境互不共享。

> Chrome 使用 **软克隆**：wrapper 仍执行 Google 签名的原始 Chrome 二进制，但传入
> 独立的 `--user-data-dir=<环境>/Browser`。这样既能隔离 Cookie/登录/扩展，又不会触发
> “Chrome-multitest1 想要使用 Chrome Safe Storage”的钥匙串密码提示（ad-hoc 硬克隆会触发）。

可用环境变量覆盖应用路径：

```bash
ZCODE_APP=/Applications/ZCode.app \
WORKBUDDY_APP=/Applications/WorkBuddy.app \
CODEBUDDY_APP="/Applications/CodeBuddy CN.app" \
QODER_APP="/Applications/Qoder CN.app" \
TRAE_APP="/Applications/Trae CN.app" \
CHROME_APP="/Applications/Google Chrome.app" \
bash scripts/setup_environments.sh phone1 phone2 phone3 phone4 phone5
```

源 App 不存在的条目会自动跳过。

### 方式 D：手动逐个创建

```bash
ENV=phone1
ENV_DIR="$HOME/TwinSpace/Data/Environments/$ENV"

twinspace clone "/Applications/Google Chrome.app" \
  --name "Chrome-$ENV" --env-group "$ENV" --data-dir "$ENV_DIR/Browser"

twinspace clone "/Applications/ZCode.app" \
  --name "ZCode-$ENV" --env-group "$ENV" \
  --set-env "TWINSPACE_BROWSER_APP_PATH=$HOME/TwinSpace/Apps/Chrome-$ENV.app"

twinspace clone "/Applications/WorkBuddy.app" \
  --name "WorkBuddy-$ENV" --env-group "$ENV" \
  --set-env "TWINSPACE_BROWSER_APP_PATH=$HOME/TwinSpace/Apps/Chrome-$ENV.app"

for spec in \
  "CodeBuddy|/Applications/CodeBuddy CN.app" \
  "Qoder|/Applications/Qoder CN.app" \
  "Trae|/Applications/Trae CN.app"; do
  name="${spec%%|*}"; app="${spec#*|}"
  twinspace clone "$app" --name "$name-$ENV" --env-group "$ENV" \
    --data-dir "$ENV_DIR/$name-$ENV" \
    --set-env "TWINSPACE_BROWSER_APP_PATH=$HOME/TwinSpace/Apps/Chrome-$ENV.app"
done
```

如果不想单独克隆 Chrome，可以省略 Chrome 克隆：内置 recipe 默认使用 `/Applications/Google Chrome.app`，仍然会用 `<环境>/Browser` 作为独立 profile。

### 启动

```bash
open "$HOME/TwinSpace/Apps/Chrome-phone1.app"
open "$HOME/TwinSpace/Apps/ZCode-phone1.app"
open "$HOME/TwinSpace/Apps/WorkBuddy-phone1.app"
open "$HOME/TwinSpace/Apps/CodeBuddy-phone1.app"
open "$HOME/TwinSpace/Apps/Qoder-phone1.app"
open "$HOME/TwinSpace/Apps/Trae-phone1.app"
```

然后在这个环境里分别用 `phone1` 登录各个 App。对 `phone2` … `phone5` 重复即可。
不要同时启动同一环境的两个同名克隆；更新/删除前先退出对应克隆。

## 4. 验证清单

1. **数据根**
   ```bash
   ps -axo pid,command | grep -E 'ZCode-phone1|WorkBuddy-phone1|CodeBuddy-phone1|Qoder-phone1|Trae-phone1'
   ```
   - ZCode Helper：`--user-data-dir=.../Environments/phone1/ZCode-phone1/UserData`
   - WorkBuddy Helper：`--user-data-dir=.../Environments/phone1/WorkBuddy-phone1/Config/app`
   - CodeBuddy Helper：`--user-data-dir=.../Environments/phone1/CodeBuddy-phone1/UserData`
   - Trae Helper：`--user-data-dir=.../Environments/phone1/Trae-phone1/UserData`
   - Qoder userData：`.../Environments/phone1/Qoder-phone1/Home/Library/Application Support/com.qodercn.app.stable`
   - Crashpad 的 `--database` 也应落在克隆 `Home` / `UserData` 下。

2. **ZCode 登录态**
   ```bash
   find "$HOME/TwinSpace/Data/Environments/phone1/ZCode-phone1/Home/.zcode" -maxdepth 3
   ```
   登录后应看到 `v2/credentials.json`、session、tasks 等；原 `~/.zcode/v2` 的 mtime 不应变化。

3. **WorkBuddy 登录态**
   ```bash
   find "$HOME/TwinSpace/Data/Environments/phone1/WorkBuddy-phone1/Home/Library/Application Support/CodeBuddyExtension" -maxdepth 5
   ```
   登录后应出现 `Data/Public/auth/workbuddy-desktop.info`；原
   `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
   的 mtime 不应变化。

4. **CodeBuddy / Qoder / Trae 登录态**
   ```bash
   # CodeBuddy / Trae: VS Code 系 userData
   find "$HOME/TwinSpace/Data/Environments/phone1/CodeBuddy-phone1/UserData/User" -maxdepth 3
   find "$HOME/TwinSpace/Data/Environments/phone1/Trae-phone1/UserData/User" -maxdepth 3

   # Qoder: appData + ~/.qoder-cn
   find "$HOME/TwinSpace/Data/Environments/phone1/Qoder-phone1/Home/Library/Application Support/com.qodercn.app.stable" -maxdepth 2
   find "$HOME/TwinSpace/Data/Environments/phone1/Qoder-phone1/Home/.qoder-cn" -maxdepth 3
   ```
   登录后 token/账号信息应只出现在克隆目录；原 App 的同名目录 mtime 不应变化。

5. **退出联动测试**
   - 在原 App 保持登录的情况下，在对应的 `-phone1` 克隆中退出登录。
   - 原 App 应保持登录；克隆的 auth/token 文件变化，原文件不变。
   - ZCode 的 `~/.zcode`、WorkBuddy 的共享 auth 文件、CodeBuddy/Trae 的 `User/globalStorage`、
     Qoder 的 `~/.qoder-cn` 都应分别验证。

6. **Keychain**
   ```bash
   security find-generic-password -s "twinspace.<prefix>.ZCode-phone1 Safe Storage"
   ```
   或在创建时加 `--set-env TWINSPACE_ISOLATION_LOG=/tmp/twinspace-isolation.log`，查看
   `keychain service ... -> twinspace...` 日志。
   WorkBuddy 的 TuringShield 服务也会被加上 clone 前缀，读写自己的 keychain item，
   不会访问原 App 的 item，因此不会再弹“找不到钥匙串/允许访问”窗口。

7. **浏览器**
   ```bash
   ps -axo pid,command | grep 'user-data-dir=.*/Environments/phone1/Browser'
   ls "$HOME/TwinSpace/Data/Environments/phone1/Browser/Default/Cookies"
   ```
   在克隆里点登录，应该打开该 profile 的 Chrome；原 Chrome 的 profile 不应出现新的登录 Cookie。

8. **ZCode OAuth 回调**
   在 `ZCode-phone1` 里发起登录，查看 LaunchServices：
   ```bash
   /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -dump \
     | grep -A6 'URL scheme:.*zcode'
   ```
   应看到 `all roles: dev.zcode.app.twinspace.N`，即当前克隆。回调会进入发起登录的克隆。

9. **WorkBuddy / CodeBuddy / Qoder / Trae 登录**
   外部登录页会在本环境的 Chrome 中打开；登录完成后，各 App 把 token 写入自己的 userData/auth 目录。
   CodeBuddy / Qoder / Trae 的 URL scheme 会在打开登录浏览器前固定到当前克隆。

## 5. 更新与删除

如果从旧版 ATBClone 升级，可以保留原数据目录：

```bash
twinspace migrate        # 创建 ~/TwinSpace -> ~/ATBClone 兼容软链
twinspace migrate --move # 物理移动并改写状态路径（高级，需重建启动器）
```


更新前先退出对应克隆（运行中会被拒绝，避免破坏 App 包）：

```bash
twinspace update ZCode-phone1
twinspace update WorkBuddy-phone1
twinspace update CodeBuddy-phone1
twinspace update Qoder-phone1
twinspace update Trae-phone1
```

`update` 会保留：

- `env_group`
- `env_dir`
- `--set-env` 写入的覆盖项（例如 Chrome 克隆路径）

删除某个环境（连同数据）：

```bash
twinspace remove Chrome-phone1 --with-data
twinspace remove ZCode-phone1 --with-data
twinspace remove WorkBuddy-phone1 --with-data
twinspace remove CodeBuddy-phone1 --with-data
twinspace remove Qoder-phone1 --with-data
twinspace remove Trae-phone1 --with-data
```

## 6. 已知限制

- **ZCode OAuth 默认回调 scheme 仍是 `zcode`**。改造通过“发起登录前把当前克隆固定为默认处理器”解决多克隆冲突；如果登录过程中又启动了原始 ZCode，它可能重新抢走默认处理器，重新发起一次登录即可。
- **Chrome 使用软克隆**：原始 Google 签名保证 Keychain ACL 正常，不会要求输入登录钥匙串密码；
  `Chrome Safe Storage` 加密密钥是全局的，但 Cookie/登录/扩展按 profile 隔离，单个环境退出不影响其他环境。
  如果要求 Chrome 的静态加密密钥也完全隔离，需要为每个环境使用独立 macOS 用户。
- **Legacy Keychain 文件共享**：克隆 Home 的 `Library/Keychains` 链接到真实目录，供 legacy API 查找钥匙串路径；现代 SecItem 和 legacy SecKeychain 的 service 都已按 clone 命名空间化，账号凭据不会互相读取。
- **Qoder 自动更新**：Qoder 没有公开的 `--disable-updates`/环境变量开关，建议在设置里关闭自动更新；若它自行升级，重新 `twinspace update Qoder-phone1`。
- **更新/删除前必须退出克隆**：运行中的 App 包被占用时，codesign/删除会失败；CLI 已加运行检测。
- **硬克隆占用逻辑空间较大**：TwinSpace 使用 `cp -Rc`（APFS copy-on-write），实际磁盘增量通常远小于 App 体积。
- **ad-hoc 签名**：`spctl` 会显示 rejected，这是本地自签的正常结果；TwinSpace 已执行 `xattr -cr`，正常 Finder/`open` 启动不受影响。启动器会主动清除从父 shell 继承的 `ELECTRON_RUN_AS_NODE`，避免 Electron 被当成纯 Node 运行。

## 7. 相关源码

- `src/twinspace/core/engines.py`
  - `_build_isolation_hook_cmd()`：SecItem + legacy SecKeychain / NSWorkspace / OAuth scheme /
    Cocoa HOME hook 隔离 dylib
  - `_resolve_template()`：`{{TWINSPACE_CLONE_NAME}}`、`{{TWINSPACE_ENV_DIR}}`、`{{TWINSPACE_INSTANCE_NUMBER}}`、`{{TWINSPACE_KEYCHAIN_PREFIX}}`
  - `_build_data_dirs_cmd()`：创建环境目录
  - `_build_preference_seeding_snippet()`：`seed_preferences` 开关，移除无条件 Keychain 软链
- `src/twinspace/core/clone_task.py`
  - `env_group`、`env_dir`、`instance_number`、`keychain_prefix`
- `src/twinspace/core/argument_prober.py`
  - Electron 启动参数白名单：`--user-data-dir`、`--extensions-dir`、`--disable-updates`
- `src/twinspace/recipes/builtin/`
  - `dev.zcode.app.yaml`
  - `com.tencent.workbuddy.mac.yaml`
  - `com.tencent.codebuddycn.yaml`
  - `com.qodercn.app.yaml`
  - `cn.trae.app.yaml`
- `src/twinspace/cli/cmd_clone.py`
  - `--env-group`、`--set-env`
- `src/twinspace/gui/services/environment_service.py`
  - 环境编排；默认分身名为 `应用名-环境名`，支持逐 App 自定义名称
- `src/twinspace/gui/windows/environment_create.py`、`src/twinspace/gui/views/environment_list.py`
  - 新建/补充环境对话框，自定义名称校验，环境卡片展示实际分身名
- `src/twinspace/core/state.py`、`src/twinspace/cli/cmd_update.py`、
  `src/twinspace/cli/cmd_remove.py`、GUI `clone_service.py`
  - 持久化环境组、环境目录和 env 覆盖项；更新/删除前运行检测
- `scripts/setup_environments.sh`
  - 一键创建多个环境的 Chrome + 全部 App
