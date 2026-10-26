"""Internationalization (i18n) module for TwinSpace.

Automatically detects the current macOS system language or environment preferences
and provides translated UI strings for CLI commands, interactive wizards, and messages.
Only English (en) and Simplified Chinese (zh) are supported; other locales fall back
to English.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

SUPPORTED_LANGUAGES = ("en", "zh")
SUPPORTED_LANGUAGES_MAP: dict[str, str] = {
    "auto": "自动 / System Default",
    "zh": "简体中文",
    "en": "English",
}

_current_lang: str | None = None

MESSAGES: dict[str, dict[str, str]] = {
    "win_wizard_icon_label": {
        "en": "App icon:",
        "zh": "应用图标：",
    },
    "win_wizard_icon_original": {
        "en": "Original app icon",
        "zh": "原应用图标",
    },
    "win_wizard_icon_choose": {
        "en": "Change icon…",
        "zh": "更换图标…",
    },
    "win_wizard_icon_reset": {
        "en": "Restore original",
        "zh": "恢复原图标",
    },
    "win_wizard_icon_invalid": {
        "en": "Please select an existing .icns file.",
        "zh": "请选择有效的 .icns 文件。",
    },
    "wizard_title": {
        "en": "🧙 TwinSpace Wizard\n",
        "zh": "🧙 TwinSpace 小向导\n",
    },
    "wizard_prompt_app_path": {
        "en": "Please enter the .app path to clone",
        "zh": "请输入要分身的 .app 路径",
    },
    "wizard_err_invalid_app_path": {
        "en": "[bold red]Error: Path does not exist or is not a .app application, please try again.[/bold red]",
        "zh": "[bold red]错误: 路径不存在或不是 .app 应用，请重新输入。[/bold red]",
    },
    "wizard_placeholder_clone_name": {
        "en": "e.g. WeChat2",
        "zh": "如 WeChat2",
    },
    "wizard_placeholder_display_name": {
        "en": "Display name in Dock/Finder",
        "zh": "Dock/Finder 显示名称",
    },
    "wizard_err_inspect_failed": {
        "en": "Failed to inspect app: {error}",
        "zh": "检测应用失败: {error}",
    },
    "wizard_detecting_app": {
        "en": "\nDetecting application...",
        "zh": "\n检测应用...",
    },
    "wizard_app_info": {
        "en": "Application: {app_name} ({bundle_id})",
        "zh": "应用: {app_name} ({bundle_id})",
    },
    "wizard_strategy_info": {
        "en": "Strategy: {strategy}\n",
        "zh": "策略: {strategy}\n",
    },
    "wizard_prompt_clone_name": {
        "en": "Clone name",
        "zh": "分身名称",
    },
    "wizard_prompt_display_name": {
        "en": "Dock/Finder display name (supports Unicode, leave empty to match clone name)",
        "zh": "Dock/Finder 显示名称（支持中文，留空与分身名称相同）",
    },
    "wizard_prompt_icon": {
        "en": "Custom icon path (.icns, leave empty for original app icon)",
        "zh": "自定义图标路径（.icns，留空使用原始 app 图标）",
    },
    "wizard_err_icon_not_found": {
        "en": "[bold red]Error: File does not exist, please try again.[/bold red]",
        "zh": "[bold red]错误: 文件不存在，请重新输入。[/bold red]",
    },
    "wizard_err_icon_not_icns": {
        "en": "[bold red]Error: Must be a .icns file, please try again.[/bold red]",
        "zh": "[bold red]错误: 必须是 .icns 文件，请重新输入。[/bold red]",
    },
    "wizard_prompt_output_dir": {
        "en": "Output directory",
        "zh": "输出目录",
    },
    "wizard_prompt_data_dir": {
        "en": "Data storage directory",
        "zh": "数据存储目录",
    },
    "wizard_prompt_use_proxy": {
        "en": "Configure proxy",
        "zh": "是否配置代理",
    },
    "wizard_prompt_proxy_host": {
        "en": "Proxy host",
        "zh": "代理地址",
    },
    "wizard_prompt_proxy_port": {
        "en": "Proxy port",
        "zh": "代理端口",
    },
    "wizard_prompt_proxy_type": {
        "en": "Proxy type",
        "zh": "代理类型",
    },
    "wizard_confirm_title": {
        "en": "\nAbout to create clone:",
        "zh": "\n即将创建分身:",
    },
    "wizard_confirm_name": {
        "en": "  Name: {clone_name}",
        "zh": "  名称: {clone_name}",
    },
    "wizard_confirm_display_name": {
        "en": "  Display Name: {display_name}",
        "zh": "  显示名称: {display_name}",
    },
    "wizard_confirm_icon": {
        "en": "  Icon: {icon_path}",
        "zh": "  图标: {icon_path}",
    },
    "wizard_confirm_target": {
        "en": "  Target: {dest_path}",
        "zh": "  目标: {dest_path}",
    },
    "wizard_confirm_data_dir": {
        "en": "  Data Dir: {data_dir}",
        "zh": "  数据目录: {data_dir}",
    },
    "wizard_confirm_strategy": {
        "en": "  Strategy: {strategy}",
        "zh": "  策略: {strategy}",
    },
    "wizard_proxy_not_configured": {
        "en": "Not configured",
        "zh": "未配置",
    },
    "wizard_confirm_proxy": {
        "en": "  Proxy: {proxy_status}\n",
        "zh": "  代理: {proxy_status}\n",
    },
    "wizard_prompt_confirm": {
        "en": "Confirm execution",
        "zh": "确认执行",
    },
    "starting_clone": {
        "en": "[bold green]Starting clone:[/bold green] {app_name} -> {clone_name}",
        "zh": "[bold green]开始创建分身:[/bold green] {app_name} -> {clone_name}",
    },
    "clone_success": {
        "en": "[bold green]Success![/bold green] Clone created at {dest_path}",
        "zh": "[bold green]成功！[/bold green] 分身创建于 {dest_path}",
    },
    "clone_error": {
        "en": "[bold red]Error:[/bold red] {error}",
        "zh": "[bold red]错误:[/bold red] {error}",
    },
    "clone_err_icon_icns": {
        "en": "[bold red]Error:[/bold red] --icon must be a .icns file.",
        "zh": "[bold red]错误:[/bold red] --icon 必须是 .icns 文件。",
    },
    "clone_err_data_dir_not_supported": {
        "en": "[bold red]Error:[/bold red] Application '{app_name}' does not support custom data directory.",
        "zh": "[bold red]错误:[/bold red] 应用 '{app_name}' 不支持自定义数据目录。",
    },
    "clone_err_ios_wrapper_unsupported": {
        "en": "iOS on Mac Wrapper applications are not supported.",
        "zh": "不支持 iOS on Mac Wrapper 应用",
    },
    "clone_err_ios_wrapper_unsupported_cli": {
        "en": "[bold red]Error:[/bold red] iOS on Mac Wrapper applications are not supported.",
        "zh": "[bold red]错误:[/bold red] 不支持 iOS on Mac Wrapper 应用。",
    },
    "clone_no_recipe_found": {
        "en": "[yellow]No pre-configured recipe found for '{bundle_id}'.[/yellow]",
        "zh": "[yellow]未找到 '{bundle_id}' 的预设规则。[/yellow]",
    },
    "clone_probing": {
        "en": "[cyan]Probing application architecture and entitlements...[/cyan]",
        "zh": "[cyan]正在探测应用架构与沙盒权限...[/cyan]",
    },
    "clone_probed_strategy": {
        "en": "[cyan]Probed Strategy:[/cyan] [bold]{strategy}[/bold] (Sandbox: {sandbox})",
        "zh": "[cyan]探测策略:[/cyan] [bold]{strategy}[/bold] (沙盒: {sandbox})",
    },
    "doctor_running_checks": {
        "en": "[bold]Running environment checks:[/bold]",
        "zh": "[bold]正在执行环境检查:[/bold]",
    },
    "doctor_missing": {
        "en": "Missing! Run 'xcode-select --install'",
        "zh": "缺失！请运行 'xcode-select --install'",
    },
    "list_no_clones": {
        "en": "[yellow]No clones found.[/yellow]",
        "zh": "[yellow]未找到任何分身应用。[/yellow]",
    },
    "list_col_name": {
        "en": "Name",
        "zh": "名称",
    },
    "list_col_source_app": {
        "en": "Source App",
        "zh": "原 APP",
    },
    "list_col_bundle_id": {
        "en": "Bundle ID",
        "zh": "Bundle ID",
    },
    "list_col_strategy": {
        "en": "Strategy",
        "zh": "策略",
    },
    "list_col_created_at": {
        "en": "Created At",
        "zh": "创建时间",
    },
    "list_col_proxy": {
        "en": "Proxy",
        "zh": "代理",
    },
    "list_col_notes": {
        "en": "Notes",
        "zh": "备注",
    },
    "list_col_destination": {
        "en": "Destination",
        "zh": "存放路径",
    },
    "list_proxy_disabled": {
        "en": "Disabled",
        "zh": "未开启",
    },
    "remove_err_not_found": {
        "en": "[red]Error:[/red] Clone '{clone_name}' not found.",
        "zh": "[red]错误:[/red] 未找到分身 '{clone_name}'。",
    },
    "remove_prompt_delete_data": {
        "en": "Also delete data directory {data_dir}?",
        "zh": "是否同时删除数据目录 {data_dir}？",
    },
    "remove_success": {
        "en": "[bold green]Success![/bold green] Removed clone '{clone_name}'",
        "zh": "[bold green]成功！[/bold green] 已删除分身 '{clone_name}'",
    },
    "update_err_not_found": {
        "en": "[red]Error:[/red] Clone '{clone_name}' not found.",
        "zh": "[red]错误:[/red] 未找到分身 '{clone_name}'。",
    },
    "update_err_source_not_found": {
        "en": "[bold red]Error:[/bold red] Source app not found at '{source_path}'",
        "zh": "[bold red]错误:[/bold red] 未在 '{source_path}' 找到源应用",
    },
    "update_starting": {
        "en": "[bold]Updating {clone_name}...[/bold]",
        "zh": "[bold]正在更新 {clone_name}...[/bold]",
    },
    "update_success": {
        "en": "[bold green]Success![/bold green] Updated {clone_name}",
        "zh": "[bold green]成功！[/bold green] 已更新 {clone_name}",
    },
    "probe_err_invalid_app": {
        "en": "[bold red]Error:[/bold red] '{app_path}' is not a valid macOS .app bundle.",
        "zh": "[bold red]错误:[/bold red] '{app_path}' 不是有效的 macOS .app 应用程序。",
    },
    "probe_err_failed": {
        "en": "[bold red]Error during probing:[/bold red] {error}",
        "zh": "[bold red]探测应用时出错:[/bold red] {error}",
    },
    "probe_title": {
        "en": "🔍 [bold]TwinSpace Deep Application Probe[/bold]",
        "zh": "🔍 [bold]TwinSpace 深度应用探测[/bold]",
    },
    "probe_row_app_name": {
        "en": "App Name",
        "zh": "应用名称",
    },
    "probe_row_bundle_id": {
        "en": "Bundle ID",
        "zh": "Bundle ID",
    },
    "probe_row_executable": {
        "en": "Executable",
        "zh": "可执行文件",
    },
    "probe_row_sandbox": {
        "en": "Sandbox Status",
        "zh": "沙盒状态",
    },
    "probe_row_frameworks": {
        "en": "Frameworks",
        "zh": "检测框架",
    },
    "probe_row_strategy": {
        "en": "Recommended Strategy",
        "zh": "推荐策略",
    },
    "probe_row_reason": {
        "en": "Analysis Notes",
        "zh": "分析说明",
    },
    "probe_yaml_header": {
        "en": "\n[bold]--- Generated Recipe YAML ---[/bold]",
        "zh": "\n[bold]--- 生成的 Recipe YAML ---[/bold]",
    },
    "probe_saved_to": {
        "en": "[bold green]✔ Saved recipe to:[/bold green] {path}",
        "zh": "[bold green]✔ 已保存分身规则至:[/bold green] {path}",
    },
    "recipe_col_bundle_id": {
        "en": "Bundle ID",
        "zh": "Bundle ID",
    },
    "recipe_col_app_name": {
        "en": "App Name",
        "zh": "应用名称",
    },
    "recipe_col_strategy": {
        "en": "Strategy",
        "zh": "策略",
    },
    "recipe_col_strip_sandbox": {
        "en": "Strip Sandbox",
        "zh": "解除沙盒",
    },
    "recipe_local_override": {
        "en": "[yellow](local override)[/yellow]",
        "zh": "[yellow](本地覆盖)[/yellow]",
    },
    "recipe_err_not_found": {
        "en": "[red]Error:[/red] Recipe for '{bundle_id}' not found.",
        "zh": "[red]错误:[/red] 未找到 '{bundle_id}' 的分身规则。",
    },
    "version_panel_title": {
        "en": "[bold green]TwinSpace System Information[/bold green]",
        "zh": "[bold green]TwinSpace 系统信息[/bold green]",
    },
    "version_row_version": {
        "en": "TwinSpace Version",
        "zh": "TwinSpace 版本",
    },
    "version_row_python": {
        "en": "Python Runtime",
        "zh": "Python 运行时",
    },
    "version_row_platform": {
        "en": "Platform",
        "zh": "操作系统平台",
    },
    "version_row_executable": {
        "en": "Executable",
        "zh": "可执行文件路径",
    },
    "version_row_state": {
        "en": "State Storage",
        "zh": "状态存储文件",
    },
    "version_row_data": {
        "en": "Data Directory",
        "zh": "数据存储目录",
    },
    "nav_clones": {
        "en": "📱 My Clones",
        "zh": "📱 我的分身",
    },
    "nav_environments": {
        "en": "🗂 My Environments",
        "zh": "🗂 我的环境",
    },
    "environment_title": {
        "en": "My Environments ({count})",
        "zh": "我的环境（{count}）",
    },
    "environment_btn_new": {
        "en": "+ New Environment",
        "zh": "+ 新建环境",
    },
    "environment_btn_open_all": {
        "en": "Open All",
        "zh": "全部打开",
    },
    "environment_app_open": {
        "en": "Open",
        "zh": "打开",
    },
    "environment_app_close": {
        "en": "Close",
        "zh": "关闭",
    },
    "environment_btn_manage": {
        "en": "Add Apps",
        "zh": "添加 App",
    },
    "environment_btn_remove": {
        "en": "Remove",
        "zh": "删除环境",
    },
    "environment_btn_update_all": {
        "en": "Update All",
        "zh": "全部更新",
    },
    "environment_btn_backup": {
        "en": "Backup",
        "zh": "备份数据",
    },
    "environment_update_confirm": {
        "en": "Rebuild every app in {name}? Quit all apps in this environment first.",
        "zh": "要重新构建 {name} 中的全部 App 吗？请先退出该环境的所有 App。",
    },
    "environment_update_title": {
        "en": "Update environment",
        "zh": "更新环境",
    },
    "environment_update_done": {
        "en": "Environment {name} updated.",
        "zh": "环境 {name} 已更新。",
    },
    "environment_update_error": {
        "en": "Some apps failed to update:\n{errors}",
        "zh": "部分 App 更新失败：\n{errors}",
    },
    "environment_backup_done": {
        "en": "Backup saved to:\n{path}",
        "zh": "备份已保存到：\n{path}",
    },
    "environment_backup_error": {
        "en": "Backup failed: {error}",
        "zh": "备份失败：{error}",
    },
    "environment_empty_title": {
        "en": "No environments yet",
        "zh": "还没有环境",
    },
    "environment_empty_hint": {
        "en": "Create one environment per phone number, then install ZCode, WorkBuddy, CodeBuddy, Qoder, Trae and Chrome into it.",
        "zh": "每个手机号建一个环境，把 ZCode、WorkBuddy、CodeBuddy、Qoder、Trae 和 Chrome 装进同一套隔离环境。",
    },
    "environment_hint": {
        "en": "Each environment has its own data, Keychain namespace and Chrome profile. Apps in this environment only open this environment's browser.",
        "zh": "每个环境使用独立的数据、Keychain 命名空间和 Chrome Profile；本环境的 App 只会打开本环境的浏览器。",
    },
    "environment_window_title": {
        "en": "New Environment",
        "zh": "新建环境",
    },
    "environment_manage_title": {
        "en": "Add Apps to {name}",
        "zh": "向 {name} 添加 App",
    },
    "environment_label_name": {
        "en": "Environment name",
        "zh": "环境名称",
    },
    "environment_name_placeholder": {
        "en": "e.g. phone1",
        "zh": "例如 phone1",
    },
    "environment_label_apps": {
        "en": "Apps to install",
        "zh": "要安装的 App",
    },
    "environment_clone_name_hint": {
        "en": "Clone names default to App-Environment and can be edited per app.",
        "zh": "分身名称默认是「应用名-环境名」，可以逐个修改。",
    },
    "environment_clone_name_required": {
        "en": "Please enter a clone name for {app}.",
        "zh": "请输入 {app} 的分身名称。",
    },
    "environment_clone_name_invalid": {
        "en": "Invalid clone name for {app}: {error}",
        "zh": "{app} 的分身名称无效：{error}",
    },
    "environment_clone_name_duplicate": {
        "en": "Clone name {name} is used more than once.",
        "zh": "分身名称 {name} 重复了。",
    },
    "environment_app_installed": {
        "en": "Installed",
        "zh": "已安装",
    },
    "environment_app_missing": {
        "en": "Not installed",
        "zh": "未安装",
    },
    "environment_app_existing": {
        "en": "Already in this environment",
        "zh": "已在此环境中",
    },
    "environment_btn_create": {
        "en": "Create Environment",
        "zh": "创建环境",
    },
    "environment_btn_add": {
        "en": "Add Missing Apps",
        "zh": "添加缺失的 App",
    },
    "environment_creating": {
        "en": "Creating {name}…",
        "zh": "正在创建 {name}…",
    },
    "environment_step": {
        "en": "Creating {app} ({current}/{total})…",
        "zh": "正在创建 {app}（{current}/{total}）…",
    },
    "environment_existing_hint": {
        "en": "This environment already exists; missing apps will be added.",
        "zh": "该环境已存在，将补充缺失的 App。",
    },
    "environment_done_title": {
        "en": "Environment Ready",
        "zh": "环境已就绪",
    },
    "environment_done_msg": {
        "en": "Environment {name} is ready.\nData: {path}\n\nOpen the apps from the Environments page.",
        "zh": "环境 {name} 已创建完成。\n数据目录：{path}\n\n可在「环境」页面打开各个 App。",
    },
    "environment_error_title": {
        "en": "Environment Creation Failed",
        "zh": "环境创建失败",
    },
    "environment_name_required": {
        "en": "Please enter an environment name.",
        "zh": "请输入环境名称。",
    },
    "environment_name_invalid": {
        "en": "Invalid environment name: {error}",
        "zh": "环境名称无效：{error}",
    },
    "environment_select_one": {
        "en": "Select at least one app.",
        "zh": "请至少选择一个 App。",
    },
    "environment_remove_title": {
        "en": "Remove Environment",
        "zh": "删除环境",
    },
    "environment_remove_msg": {
        "en": "Remove environment {name}? Its app clones will be deleted.",
        "zh": "确定删除环境 {name}？该环境的 App 分身穿会一起删除。",
    },
    "environment_remove_data_msg": {
        "en": "Also delete all environment data (browser profile, logins, caches)?",
        "zh": "是否同时删除环境数据（浏览器 Profile、登录态、缓存）？",
    },
    "environment_remove_error": {
        "en": "Failed to remove environment: {error}",
        "zh": "删除环境失败：{error}",
    },
    "environment_running": {
        "en": "Running",
        "zh": "运行中",
    },
    "environment_not_running": {
        "en": "Not running",
        "zh": "未运行",
    },
    "environment_path": {
        "en": "Path: {path}",
        "zh": "路径：{path}",
    },
    "environment_no_missing_apps": {
        "en": "All selected apps already exist in this environment.",
        "zh": "所选 App 都已在此环境中。",
    },
    "env_err_not_found": {
        "en": "Environment '{name}' not found.",
        "zh": "未找到环境 '{name}'。",
    },
    "env_list_empty": {
        "en": "No environments yet. Create one with: twinspace env create <name>",
        "zh": "还没有环境。可使用 twinspace env create <名称> 创建",
    },
    "env_list_title": {
        "en": "TwinSpace environments ({count})",
        "zh": "TwinSpace 环境 ({count})",
    },
    "env_col_name": {
        "en": "Name",
        "zh": "名称",
    },
    "env_col_apps": {
        "en": "Apps",
        "zh": "应用",
    },
    "env_col_state": {
        "en": "State",
        "zh": "状态",
    },
    "env_col_directory": {
        "en": "Directory",
        "zh": "目录",
    },
    "env_state_running": {
        "en": "running",
        "zh": "运行中",
    },
    "env_state_stopped": {
        "en": "stopped",
        "zh": "未运行",
    },
    "env_status_checking": {
        "en": "checking",
        "zh": "检查中",
    },
    "env_status_existing": {
        "en": "already present",
        "zh": "已存在",
    },
    "env_status_creating": {
        "en": "creating",
        "zh": "创建中",
    },
    "env_status_created": {
        "en": "created",
        "zh": "已创建",
    },
    "env_status_updating": {
        "en": "updating",
        "zh": "更新中",
    },
    "env_status_updated": {
        "en": "updated",
        "zh": "已更新",
    },
    "env_status_failed": {
        "en": "failed",
        "zh": "失败",
    },
    "env_no_supported_apps": {
        "en": "No supported apps are installed.",
        "zh": "未检测到受支持的应用。",
    },
    "env_plan_title": {
        "en": "Environment plan: {name}",
        "zh": "环境计划: {name}",
    },
    "env_col_app": {
        "en": "App",
        "zh": "应用",
    },
    "env_col_clone_name": {
        "en": "Clone name",
        "zh": "分身名称",
    },
    "env_col_source": {
        "en": "Source",
        "zh": "来源",
    },
    "env_source_missing": {
        "en": "missing: {path}",
        "zh": "未安装: {path}",
    },
    "env_create_missing_apps": {
        "en": "Some apps are not installed; nothing was created.",
        "zh": "部分应用未安装，未创建任何内容。",
    },
    "env_created": {
        "en": "Environment '{name}' is ready ({count} new app(s)) at {path}",
        "zh": "环境 '{name}' 已就绪（新增 {count} 个应用），位于 {path}",
    },
    "env_open_errors": {
        "en": "Some apps could not be opened:",
        "zh": "部分应用无法打开：",
    },
    "env_opened": {
        "en": "Opened environment '{name}'.",
        "zh": "已打开环境 '{name}'。",
    },
    "env_remove_confirm": {
        "en": "Remove environment '{name}' ({count} app(s))?",
        "zh": "确定删除环境 '{name}'（{count} 个应用）？",
    },
    "env_remove_errors": {
        "en": "Environment removed with errors:",
        "zh": "环境已删除，但存在错误：",
    },
    "env_removed": {
        "en": "Environment '{name}' removed.",
        "zh": "环境 '{name}' 已删除。",
    },
    "env_update_errors": {
        "en": "Some apps failed to update:",
        "zh": "部分应用更新失败：",
    },
    "env_updated": {
        "en": "Environment '{name}' updated.",
        "zh": "环境 '{name}' 已更新。",
    },
    "env_export_wrote": {
        "en": "Wrote {output}",
        "zh": "已写入 {output}",
    },
    "env_import_dry_title": {
        "en": "Environment: {name}",
        "zh": "环境: {name}",
    },
    "env_import_row": {
        "en": "  - {app_key}: {clone} (state: {state})",
        "zh": "  - {app_key}: {clone}（状态: {state}）",
    },
    "env_import_state_existing": {
        "en": "existing",
        "zh": "已存在",
    },
    "env_import_state_new": {
        "en": "new",
        "zh": "新增",
    },
    "env_import_clone_default": {
        "en": "(default)",
        "zh": "（默认）",
    },
    "env_import_all_present": {
        "en": "Environment '{name}' already has all apps from this file.",
        "zh": "环境 '{name}' 已包含此文件中的全部应用。",
    },
    "env_templates_title": {
        "en": "Built-in templates",
        "zh": "内置模板",
    },
    "env_col_template": {
        "en": "Template",
        "zh": "模板",
    },
    "env_backup_wrote": {
        "en": "Backup written to {path}",
        "zh": "备份已写入 {path}",
    },
    "env_restore_confirm": {
        "en": "Restore {archive} into environment '{name}'? Existing files are overwritten.",
        "zh": "将 {archive} 恢复到环境 '{name}'？现有文件将被覆盖。",
    },
    "env_restore_done_list": {
        "en": "Restored: {apps}",
        "zh": "已恢复: {apps}",
    },
    "env_restore_errors": {
        "en": "Errors:",
        "zh": "错误：",
    },
    "env_restored": {
        "en": "Environment '{name}' restored.",
        "zh": "环境 '{name}' 已恢复。",
    },
    "env_err_param_one_key": {
        "en": "Specify at least one app key.",
        "zh": "请至少指定一个应用标识。",
    },
    "env_err_param_unknown_key": {
        "en": "Unknown app key: {key}",
        "zh": "未知应用标识: {key}",
    },
    "env_err_param_clone_format": {
        "en": "Use --clone-name APP=NAME.",
        "zh": "请使用 --clone-name 应用=名称 的格式。",
    },
    "env_browser_section": {
        "en": "Browser Binding",
        "zh": "浏览器绑定",
    },
    "env_browser_mode_chrome": {
        "en": "Environment Chrome (default)",
        "zh": "环境专属 Chrome（默认）",
    },
    "env_browser_mode_system": {
        "en": "System default browser (no binding)",
        "zh": "系统默认浏览器（不绑定）",
    },
    "env_browser_mode_external": {
        "en": "External browser (.app)",
        "zh": "外部浏览器（.app）",
    },
    "env_browser_path_placeholder": {
        "en": "Pick or enter a browser .app path",
        "zh": "选择或输入浏览器 .app 路径",
    },
    "env_browser_browse": {
        "en": "Browse…",
        "zh": "浏览…",
    },
    "env_browser_hint_chrome": {
        "en": "Links and OAuth from other apps in this environment open in this environment's own Chrome clone, with the environment's isolated profile.",
        "zh": "环境内其他应用的链接与 OAuth 将使用本环境的 Chrome 分身打开，Profile 隔离保存在环境内。",
    },
    "env_browser_hint_system": {
        "en": "No binding: links open in the macOS default browser.",
        "zh": "不绑定浏览器：链接将打开 macOS 系统默认浏览器。",
    },
    "env_browser_hint_external": {
        "en": "Links open in the external browser; the browsing profile stays isolated inside the environment.",
        "zh": "环境内应用的链接将用该外部浏览器打开，浏览 Profile 隔离保存在环境内。",
    },
    "env_browser_invalid": {
        "en": "Please pick a valid macOS .app browser bundle.",
        "zh": "请选择有效的 macOS .app 浏览器应用。",
    },
    "env_btn_export": {
        "en": "Export Template",
        "zh": "导出模板",
    },
    "env_btn_restore": {
        "en": "Restore Backup",
        "zh": "恢复备份",
    },
    "env_btn_import": {
        "en": "Import Template",
        "zh": "导入模板",
    },
    "env_export_done": {
        "en": "Template exported to: {path}",
        "zh": "模板已导出：{path}",
    },
    "env_restore_confirm_gui": {
        "en": "Restoring will overwrite existing data in environment '{name}' (a safety backup is created first). Continue?",
        "zh": "恢复将覆盖环境 “{name}” 内的现有数据（会先自动创建安全备份）。确定继续吗？",
    },
    "env_restore_done": {
        "en": "Restored: {apps}",
        "zh": "已恢复：{apps}",
    },
    "env_restore_safety": {
        "en": "Safety backup: {path}",
        "zh": "安全备份：{path}",
    },
    "env_import_confirm": {
        "en": "Import template '{name}'? Apps to add: {apps} (existing apps are skipped).",
        "zh": "导入模板 “{name}”？将新增以下应用：{apps}（已存在的自动跳过）。",
    },
    "env_import_done": {
        "en": "Imported {count} app(s) into environment '{name}'.",
        "zh": "已导入 {count} 个应用到环境 “{name}”。",
    },
    "env_import_no_new": {
        "en": "All apps from this template already exist in this environment.",
        "zh": "模板中的应用都已存在于该环境。",
    },
    "env_err_param_setenv_format": {
        "en": "Use --set-env APP=KEY=VALUE.",
        "zh": "请使用 --set-env 应用=键=值 的格式。",
    },
    "env_err_param_browser_app": {
        "en": "--browser must point to a macOS .app bundle.",
        "zh": "--browser 必须指向一个 macOS .app 应用。",
    },
    "env_err_param_clone_empty": {
        "en": "Clone name for {key} cannot be empty.",
        "zh": "{key} 的分身名称不能为空。",
    },
    "nav_recipes": {
        "en": "📖 Recipes",
        "zh": "📖 分身规则",
    },
    "nav_probe": {
        "en": "🔍 App Probe",
        "zh": "🔍 应用探测",
    },
    "nav_doctor": {
        "en": "🩺 Doctor",
        "zh": "🩺 环境自检",
    },
    "nav_logs": {
        "en": "📋 Logs",
        "zh": "📋 运行日志",
    },
    "nav_settings": {
        "en": "⚙️ Settings",
        "zh": "⚙️ 全局设置",
    },
    "topbar_view_grid": {
        "en": "🔲 Grid View",
        "zh": "🔲 卡片视图",
    },
    "topbar_view_list": {
        "en": "📋 List View",
        "zh": "📋 列表视图",
    },
    "topbar_search_placeholder": {
        "en": "🔍 Search...",
        "zh": "🔍 搜索...",
    },
    "topbar_btn_refresh": {
        "en": "🔄 Refresh",
        "zh": "🔄 刷新",
    },
    "btn_launch": {
        "en": "▶️ Launch",
        "zh": "▶️ 启动",
    },
    "btn_open_clone_dir": {
        "en": "📁 Open Folder",
        "zh": "📁 打开分身所在目录",
    },
    "btn_update": {
        "en": "🔄 Update",
        "zh": "🔄 更新",
    },
    "btn_updating": {
        "en": "🔄 Updating...",
        "zh": "🔄 更新中...",
    },
    "btn_edit": {
        "en": "✏️ Edit",
        "zh": "✏️ 编辑",
    },
    "btn_detail": {
        "en": "ℹ️ Details",
        "zh": "ℹ️ 详情",
    },
    "btn_delete": {
        "en": "🗑️ Delete",
        "zh": "🗑️ 删除",
    },
    "btn_open_dir_short": {
        "en": "Dir",
        "zh": "目录",
    },
    "btn_update_short": {
        "en": "Update",
        "zh": "更新",
    },
    "btn_edit_short": {
        "en": "Edit",
        "zh": "编辑",
    },
    "btn_detail_short": {
        "en": "Info",
        "zh": "详情",
    },
    "btn_delete_short": {
        "en": "Delete",
        "zh": "删除",
    },
    "btn_batch_update": {
        "en": "🔄 Update ({count})",
        "zh": "🔄 批量更新 ({count})",
    },
    "btn_batch_delete": {
        "en": "🗑️ Delete ({count})",
        "zh": "🗑️ 批量删除 ({count})",
    },
    "btn_updating_progress": {
        "en": "🔄 Updating ({current}/{total})...",
        "zh": "🔄 正在更新 ({current}/{total})...",
    },
    "btn_deleting_progress": {
        "en": "🗑️ Deleting ({current}/{total})...",
        "zh": "🗑️ 正在删除 ({current}/{total})...",
    },
    "btn_browse_app": {
        "en": "📂 Browse App...",
        "zh": "📂 浏览应用...",
    },
    "btn_browse_dir": {
        "en": "📂 Browse...",
        "zh": "📂 浏览目录...",
    },
    "btn_save_changes": {
        "en": "💾 Save Changes",
        "zh": "💾 保存修改",
    },
    "btn_cancel": {
        "en": "Cancel",
        "zh": "取消",
    },
    "btn_close": {
        "en": "Close",
        "zh": "关闭",
    },
    "btn_new_clone": {
        "en": "+ New Clone",
        "zh": "+ 新建分身",
    },
    "btn_new_recipe": {
        "en": "+ New Recipe",
        "zh": "+ 新建规则",
    },
    "card_strategy_soft": {
        "en": "[Soft Clone]",
        "zh": "[软包装克隆]",
    },
    "card_strategy_hard": {
        "en": "[Hard Clone]",
        "zh": "[物理克隆]",
    },
    "card_label_source": {
        "en": "Source App: {source_app}",
        "zh": "源应用: {source_app}",
    },
    "card_label_path": {
        "en": "Path: {path}",
        "zh": "路径: {path}",
    },
    "card_label_proxy": {
        "en": "Proxy: {proxy_info}",
        "zh": "代理: {proxy_info}",
    },
    "card_proxy_disabled": {
        "en": "Disabled",
        "zh": "未启用代理",
    },
    "view_clones_title": {
        "en": "📱 My Clones ({count})",
        "zh": "📱 我的分身 ({count})",
    },
    "view_clones_title_filtered": {
        "en": "📱 My Clones (Filtered {filter_count}/{total_count})",
        "zh": "📱 我的分身 (筛选 {filter_count}/{total_count})",
    },
    "view_clones_search_placeholder": {
        "en": "🔍 Search clone / source app...",
        "zh": "🔍 搜索分身 / 源应用...",
    },
    "view_clones_filter_all": {
        "en": "All",
        "zh": "全部",
    },
    "view_clones_filter_hard": {
        "en": "Hard",
        "zh": "物理克隆",
    },
    "view_clones_filter_soft": {
        "en": "Soft",
        "zh": "软包装",
    },
    "view_clones_filter_proxy": {
        "en": "Proxy On",
        "zh": "启用代理",
    },
    "view_clones_sort_newest": {
        "en": "Newest",
        "zh": "最新",
    },
    "view_clones_sort_name": {
        "en": "Name A–Z",
        "zh": "名称 A–Z",
    },
    "view_clones_sort_oldest": {
        "en": "Oldest",
        "zh": "最早",
    },
    "view_clones_empty_hint": {
        "en": "No cloned applications yet.",
        "zh": "暂无分身应用",
    },
    "view_clones_empty_cta_env": {
        "en": "+ Create First Environment (recommended)",
        "zh": "+ 创建第一个隔离环境（推荐）",
    },
"view_clones_empty_cta": {
        "en": "Click '+ New Clone' above to create your first clone.",
        "zh": "点击上方「+ 新建分身」立即创建",
    },
    "view_recipes_title": {
        "en": "📖 Clone Recipes ({count})",
        "zh": "📖 分身规则 ({count})",
    },
    "view_recipes_title_filtered": {
        "en": "📖 Clone Recipes (Filtered {filter_count}/{total_count})",
        "zh": "📖 分身规则 (筛选 {filter_count}/{total_count})",
    },
    "view_recipes_search_placeholder": {
        "en": "🔍 Search recipes / Bundle ID...",
        "zh": "🔍 搜索应用规则 / Bundle ID...",
    },
    "view_recipes_filter_all": {
        "en": "All",
        "zh": "全部",
    },
    "view_recipes_filter_builtin": {
        "en": "Built-in",
        "zh": "内置",
    },
    "view_recipes_filter_custom": {
        "en": "Custom",
        "zh": "自定义",
    },
    "view_recipes_sort_name_asc": {
        "en": "Name A–Z",
        "zh": "名称 A–Z",
    },
    "view_recipes_sort_name_desc": {
        "en": "Name Z–A",
        "zh": "名称 Z–A",
    },
    "view_recipes_sort_strategy": {
        "en": "Strategy",
        "zh": "策略",
    },
    "view_recipes_empty_hint": {
        "en": "No matching clone recipes found. Click '+ New Recipe' to add custom rules.",
        "zh": "暂无匹配的分身规则，可点击右上角「+ 新建规则」添加自定义规则。",
    },
    "settings_btn_save": {
        "en": "💾 Save Preferences",
        "zh": "💾 保存设置",
    },
    "settings_card_storage": {
        "en": "📁 Storage & Data Management",
        "zh": "📁 数据与存储管理",
    },
    "settings_label_apps_dir": {
        "en": "Cloned Apps Directory: {path}",
        "zh": "分身应用存放目录: {path}",
    },
    "settings_label_data_dir": {
        "en": "Isolated Data Directory: {path}",
        "zh": "数据隔离存放目录: {path}",
    },
    "settings_btn_open_finder": {
        "en": "📂 Reveal in Finder (~/TwinSpace)",
        "zh": "📂 在 Finder 中打开数据目录 (~/TwinSpace)",
    },
    "settings_label_root": {
        "en": "Root Workspace:",
        "zh": "根工作目录:",
    },
    "settings_hint_paths": {
        "en": "（Cloned apps, isolated data, and recipes will be stored under this directory）",
        "zh": "（分身应用、隔离数据及分身规则将自动归档在该根工作目录下）",
    },
    "settings_card_proxy": {
        "en": "🌐 Default Proxy Configuration (Optional)",
        "zh": "🌐 默认代理配置 (可选)",
    },
    "settings_switch_proxy_default": {
        "en": "Enable proxy by default when creating clones",
        "zh": "创建分身时默认启用代理",
    },
    "settings_card_tray": {
        "en": "🪟 Window & Tray Preferences",
        "zh": "🪟 窗口与系统托盘偏好",
    },
    "settings_switch_minimize_to_tray": {
        "en": "Minimize to System Tray",
        "zh": "最小化到系统托盘",
    },
    "settings_hint_minimize_to_tray": {
        "en": "Hide main window to menu bar when clicking minimize button (-)",
        "zh": "点击窗口最小化按钮（-）时隐藏到顶部菜单栏状态栏",
    },
    "tray_menu_show": {
        "en": "Show TwinSpace",
        "zh": "显示主界面",
    },
    "tray_menu_quit": {
        "en": "Quit TwinSpace",
        "zh": "退出 TwinSpace",
    },
    "settings_card_language": {
        "en": "🌐 Interface Language",
        "zh": "🌐 界面语言",
    },
    "settings_label_language": {
        "en": "Language:",
        "zh": "界面语言:",
    },
    "settings_hint_language": {
        "en": "Switch UI language in real time without restarting the application.",
        "zh": "切换界面语言后即时生效，无需重启应用。",
    },
    "settings_card_about": {
        "en": "ℹ️ About TwinSpace",
        "zh": "ℹ️ 关于 TwinSpace",
    },
    "settings_label_version": {
        "en": "TwinSpace Version: v{ver}",
        "zh": "TwinSpace 版本: v{ver}",
    },
    "settings_label_python": {
        "en": "Python Runtime: {ver} ({arch})",
        "zh": "Python 核心: {ver} ({arch})",
    },
    "settings_label_os": {
        "en": "macOS Architecture: {ver}",
        "zh": "macOS 系统架构: {ver}",
    },
    "doctor_summary_all_passed": {
        "en": "✅ All environment checks passed ({passed}/{total})",
        "zh": "✅ 所有环境检测项全部通过 ({passed}/{total})",
    },
    "doctor_summary_issues_found": {
        "en": "⚠️ Found {count} unready environment component(s), please check hints below.",
        "zh": "⚠️ 发现 {count} 项未就绪环境组件，请参考列表修复建议",
    },
    "doctor_col_status": {
        "en": "Status",
        "zh": "状态",
    },
    "doctor_col_item": {
        "en": "Item",
        "zh": "检测项",
    },
    "doctor_col_details": {
        "en": "Current Environment Details",
        "zh": "当前环境详情",
    },
    "doctor_col_hint": {
        "en": "Recommendation / Hint",
        "zh": "修复建议 / 说明",
    },
    "doctor_status_failed": {
        "en": "❌ Missing",
        "zh": "❌ 缺失",
    },
    "doctor_btn_recheck": {
        "en": "🔄 Recheck",
        "zh": "🔄 重新检测",
    },
    "doctor_summary_initial": {
        "en": "⏳ Click Recheck to start diagnostics",
        "zh": "⏳ 点击右上角“重新检测”按钮开始检测",
    },
    "doctor_status_ok": {
        "en": "✅ Passed",
        "zh": "✅ 正常",
    },
    "doctor_status_missing": {
        "en": "❌ Missing",
        "zh": "❌ 缺失",
    },
    "doctor_btn_install_xcode": {
        "en": "📦 Install Xcode Command Line Tools",
        "zh": "📦 一键安装 Xcode 命令行工具",
    },
    "doctor_hint_xcode_select": {
        "en": "Click 'Install Xcode Command Line Tools' above or run: xcode-select --install",
        "zh": "请点击上方【一键安装】或在终端执行: xcode-select --install",
    },
    "doctor_dialog_install_title": {
        "en": "Xcode Command Line Tools Installation",
        "zh": "Xcode 命令行工具安装指引",
    },
    "doctor_dialog_install_msg": {
        "en": "The macOS native installation dialog has been opened.\n\nPlease follow Apple's system prompt to complete the download and installation (~2GB).\n\nOnce the installation completes, please click the [🔄 Recheck] button.",
        "zh": "已为您唤起 macOS 系统原生安装弹窗。\n\n请在系统弹窗中点击【安装】并等待下载安装完成（约 2GB）。\n\n安装完成后，请点击界面右上角【🔄 重新检测】按钮。",
    },
    "doctor_dialog_install_already_msg": {
        "en": "Xcode Command Line Tools installation is already in progress or already installed.\n\nPlease complete the system installer or click [🔄 Recheck].",
        "zh": "Xcode 命令行工具已在安装中或已安装。\n\n请完成系统安装流程或点击【🔄 重新检测】。",
    },
    "doctor_dialog_install_error_msg": {
        "en": "Failed to launch Xcode installer:\n{error}\n\nPlease try running in Terminal: xcode-select --install",
        "zh": "唤起 Xcode 安装程序失败：\n{error}\n\n请尝试在终端中执行: xcode-select --install",
    },
    "doctor_item_apps_dir": {
        "en": "Application Directory Permissions",
        "zh": "应用程序目录权限",
    },
    "doctor_item_data_dir": {
        "en": "Data Storage Directory Permissions",
        "zh": "数据存储目录权限",
    },
    "doctor_rw_normal": {
        "en": "Read/Write OK",
        "zh": "读写正常",
    },
    "doctor_rw_failed": {
        "en": "Read/Write Failed",
        "zh": "读写异常",
    },
    "doctor_hint_dir_perm": {
        "en": "Check directory permissions: chmod u+rwx {path}",
        "zh": "检查目录权限: chmod u+rwx {path}",
    },
    "probe_btn_start": {
        "en": "🔍 Start Probe",
        "zh": "🔍 开始探测",
    },
    "probe_card_target": {
        "en": "📦 Select Target Application",
        "zh": "📦 选择目标应用",
    },
    "probe_input_placeholder": {
        "en": "Enter application path or browse /Applications...",
        "zh": "请输入应用路径或浏览 /Applications...",
    },
    "probe_card_results": {
        "en": "🔬 Prober Analysis Report",
        "zh": "🔬 应用探测分析报告",
    },
    "probe_btn_save_recipe": {
        "en": "💾 Save as Custom Recipe",
        "zh": "💾 保存为自定义 Recipe 规则",
    },
    "probe_sandbox_yes": {
        "en": "Enabled (App Sandbox)",
        "zh": "已开启 (App Sandbox)",
    },
    "probe_sandbox_no": {
        "en": "Disabled / Not sandboxed",
        "zh": "未启用 / 无沙盒",
    },
    "probe_saved_success": {
        "en": "✅ Saved to ~/TwinSpace/recipes",
        "zh": "✅ 已保存到 ~/TwinSpace/recipes",
    },
    "view_recipes_col_origin": {
        "en": "Origin",
        "zh": "规则来源",
    },
    "view_recipes_origin_builtin": {
        "en": "Built-in",
        "zh": "内置规则",
    },
    "view_recipes_origin_custom": {
        "en": "Custom",
        "zh": "自定义",
    },
    "logs_title_total": {
        "en": "📋 Logs ({total} lines)",
        "zh": "📋 运行日志 ({total} 行)",
    },
    "logs_title_filtered": {
        "en": "📋 Logs (Filtered {count}/{total} lines)",
        "zh": "📋 运行日志 (筛选 {count}/{total} 行)",
    },
    "logs_search_placeholder": {
        "en": "🔍 Search log keywords...",
        "zh": "🔍 搜索日志关键字...",
    },
    "logs_btn_clear": {
        "en": "🗑️ Clear Logs",
        "zh": "🗑️ 清空日志",
    },
    "dialog_info_title": {
        "en": "Information",
        "zh": "提示",
    },
    "dialog_error_title": {
        "en": "Error",
        "zh": "错误",
    },
    "dialog_settings_saved_title": {
        "en": "Settings Saved",
        "zh": "设置已保存",
    },
    "dialog_settings_saved_msg": {
        "en": "Preferences have been updated successfully.",
        "zh": "全局偏好设置已成功更新生效。",
    },
    "dialog_select_root_dir_title": {
        "en": "Select TwinSpace Root Workspace Directory",
        "zh": "选择 TwinSpace 根工作目录",
    },
    "dialog_select_app_title": {
        "en": "Select macOS Application",
        "zh": "选择要分身的 macOS 应用程序",
    },
    "dialog_select_dest_dir_title": {
        "en": "Select Destination Directory",
        "zh": "选择分身存放目标目录",
    },
    "dialog_select_data_dir_title": {
        "en": "Select Data Directory",
        "zh": "选择数据存放目录",
    },
    "dialog_launch_error_title": {
        "en": "Launch Error",
        "zh": "启动失败",
    },
    "dialog_launch_error_not_found": {
        "en": "Clone application does not exist at {path}",
        "zh": "分身应用文件不存在于: {path}",
    },
    "dialog_launch_error_failed": {
        "en": "Failed to open application: {error}",
        "zh": "启动应用失败: {error}",
    },
    "dialog_update_error_title": {
        "en": "Update Error",
        "zh": "更新失败",
    },
    "dialog_delete_confirm_title": {
        "en": "Delete Clone",
        "zh": "删除分身",
    },
    "dialog_delete_confirm_msg": {
        "en": "Are you sure you want to remove '{name}'?",
        "zh": "确定要删除分身应用 '{name}' 吗？",
    },
    "dialog_delete_data_confirm_title": {
        "en": "Delete Data Directory",
        "zh": "删除数据目录",
    },
    "dialog_delete_data_confirm_msg": {
        "en": "Also delete isolated data directory at:\n{path}?",
        "zh": "是否同时删除该分身的独立数据目录：\n{path}？",
    },
    "dialog_batch_delete_confirm_title": {
        "en": "Confirm Batch Deletion",
        "zh": "确认批量删除",
    },
    "dialog_batch_delete_confirm_msg": {
        "en": "Are you sure you want to delete {count} selected clones?\n{names}",
        "zh": "确定要删除选中的 {count} 个分身应用吗？\n{names}",
    },
    "dialog_batch_delete_data_confirm_title": {
        "en": "Clean Data Directories",
        "zh": "清理用户数据目录",
    },
    "dialog_batch_delete_data_confirm_msg": {
        "en": "Do you also want to delete the user data and config directories for these {count} clones?\nSelecting 'Cancel' will keep data directories and only remove the clone applications.",
        "zh": "是否同时清理这 {count} 个分身的用户数据与配置目录？\n选择“取消”将保留数据目录，仅删除分身应用本体。",
    },
    "dialog_batch_summary_title": {
        "en": "Batch Operation Results",
        "zh": "批量操作结果",
    },
    "dialog_recipe_delete_confirm_title": {
        "en": "Delete Recipe",
        "zh": "删除规则",
    },
    "dialog_recipe_delete_confirm_msg": {
        "en": "Are you sure you want to delete custom recipe '{name}'?",
        "zh": "确定要删除自定义规则 '{name}' 吗？",
    },
    "dialog_recipe_batch_delete_confirm_title": {
        "en": "Confirm Batch Deletion",
        "zh": "确认批量删除规则",
    },
    "dialog_recipe_batch_delete_confirm_msg": {
        "en": "Are you sure you want to delete {count} selected custom recipes?\n{names}",
        "zh": "确定要删除选中的 {count} 个自定义规则吗？\n{names}",
    },
    "dialog_recipe_batch_delete_confirm_mixed_title": {
        "en": "Confirm Batch Deletion",
        "zh": "确认批量删除规则",
    },
    "dialog_recipe_batch_delete_confirm_mixed_msg": {
        "en": "Selected items contain {custom_count} custom recipe(s) and {builtin_count} built-in recipe(s).\nThe system will delete the custom recipes and skip built-in recipes.\n\nRecipes to delete:\n{names}\n\nDo you want to continue?",
        "zh": "选中的项目中包含 {custom_count} 个自定义规则与 {builtin_count} 个内置规则。\n系统将删除自定义规则并自动跳过内置规则。\n\n待删除规则：\n{names}\n\n是否继续？",
    },
    "dialog_batch_summary_msg": {
        "en": "Operation completed: {success} succeeded, {failed} failed.\n\nFailure details:\n{errors}",
        "zh": "操作完成：{success} 个成功，{failed} 个失败。\n\n失败详情：\n{errors}",
    },
    "dialog_probe_input_required": {
        "en": "Please select or enter an application path first.",
        "zh": "请先选择或输入应用程序路径。",
    },
    "dialog_probe_failed_title": {
        "en": "Probe Failed",
        "zh": "探测失败",
    },
    "dialog_validation_error_title": {
        "en": "Validation Error",
        "zh": "输入校验失败",
    },
    "dialog_validation_error_msg": {
        "en": "Bundle ID and App Name cannot be empty.",
        "zh": "Bundle ID 和应用名称不能为空。",
    },
    "dialog_clone_success_title": {
        "en": "Clone Created Successfully",
        "zh": "分身创建成功",
    },
    "dialog_clone_success_msg": {
        "en": "Clone application created successfully at:\n{path}",
        "zh": "分身应用已成功创建并就绪：\n{path}",
    },
    "dialog_clone_error_title": {
        "en": "Clone Failed",
        "zh": "创建分身失败",
    },
    "dialog_input_required_title": {
        "en": "Input Required",
        "zh": "输入提示",
    },
    "dialog_input_required_app_path": {
        "en": "Please select or enter the source .app bundle path.",
        "zh": "请先选择或输入源 .app 应用程序路径。",
    },
    "dialog_input_required_clone_name": {
        "en": "Please enter a valid clone name.",
        "zh": "请输入有效的分身应用名称。",
    },
    "dialog_input_required_dest_dir": {
        "en": "Please enter or select a valid destination directory.",
        "zh": "请选择或输入有效的分身存放目录。",
    },
    "win_wizard_title": {
        "en": "Clone App Wizard",
        "zh": "分身创建向导",
    },
    "win_wizard_step1_header": {
        "en": "Step 1 of 7: Select Source Application",
        "zh": "步骤 1/7: 选择源应用程序",
    },
    "win_wizard_step1_desc": {
        "en": "Choose the .app bundle you want to clone:",
        "zh": "请选择要创建分身的 .app 应用程序:",
    },
    "win_wizard_step2_header": {
        "en": "Step 2 of 7: Confirm Recipe & Strategy",
        "zh": "步骤 2/7: 确认分身规则与克隆策略",
    },
    "win_wizard_step2_select_strat": {
        "en": "Cloning Strategy:",
        "zh": "克隆策略:",
    },
    "win_wizard_step2_select_injection": {
        "en": "Injection Mode:",
        "zh": "注入模式:",
    },
    "win_wizard_step2_origin_builtin": {
        "en": "✅ Matched built-in Recipe from library.",
        "zh": "✅ 已匹配官方预设规则。",
    },
    "win_wizard_step2_origin_probe": {
        "en": "ℹ️ No built-in Recipe found — strategy auto-detected via Probe analysis.",
        "zh": "ℹ️ 未找到内置规则，已通过深度探测自动推导策略。",
    },
    "win_wizard_step3_header": {
        "en": "Step 3 of 7: Clone Name & Display Name",
        "zh": "步骤 3/7: 设置分身名称与显示名称",
    },
    "win_wizard_step3_clone_name": {
        "en": "Clone Name:",
        "zh": "分身名称:",
    },
    "win_wizard_step3_display_name": {
        "en": "Display Name:",
        "zh": "显示名称:",
    },
    "win_wizard_step3_language": {
        "en": "Language:",
        "zh": "语言环境:",
    },
    "win_edit_language": {
        "en": "Language:",
        "zh": "语言环境:",
    },
    "detail_label_language": {
        "en": "Language",
        "zh": "语言环境",
    },
    "detail_label_injection": {
        "en": "Injection Strategy",
        "zh": "注入模式",
    },
    "lang_system": {
        "en": "Follow System (Default)",
        "zh": "跟随系统（默认）",
    },
    "lang_zh_hans": {
        "en": "Simplified Chinese (zh-Hans)",
        "zh": "简体中文 (zh-Hans)",
    },
    "lang_en": {
        "en": "English (en)",
        "zh": "英语 (en)",
    },
    "win_wizard_step4_header": {
        "en": "Step 4 of 7: Destination Directory",
        "zh": "步骤 4/7: 选择分身存放目录",
    },
    "win_wizard_step4_desc": {
        "en": "Target directory where the cloned .app will be saved:",
        "zh": "目标分身 .app 将被生成并保存至该目录下:",
    },
    "win_wizard_step5_header": {
        "en": "Step 5 of 7: Data Directory Isolation",
        "zh": "步骤 5/7: 数据隔离存放目录",
    },
    "win_wizard_step5_supported": {
        "en": "✅ Data Directory isolation supported.",
        "zh": "✅ 支持独立数据目录隔离。",
    },
    "win_wizard_step5_unsupported": {
        "en": "⚠️ Custom Data Directory is not supported by this Recipe strategy.",
        "zh": "⚠️ 当前策略暂不支持自定义数据目录。",
    },
    "win_wizard_step5_label": {
        "en": "Data Directory:",
        "zh": "数据目录:",
    },
    "win_wizard_step6_header": {
        "en": "Step 6 of 7: Network Proxy Configuration",
        "zh": "步骤 6/7: 独立网络代理配置",
    },
    "win_wizard_step6_switch": {
        "en": "Enable Dedicated Proxy",
        "zh": "为该分身启用专属独立代理",
    },
    "win_wizard_step6_type_host_port": {
        "en": "Type/Host/Port:",
        "zh": "类型/地址/端口:",
    },
    "win_wizard_step7_header": {
        "en": "Step 7 of 7: Confirmation & Execution",
        "zh": "步骤 7/7: 确认配置并执行创建",
    },
    "win_wizard_status_ready": {
        "en": "Ready to clone.",
        "zh": "准备就绪，点击下方按钮开始创建。",
    },
    "win_wizard_status_cloning": {
        "en": "⏳ Cloning application in background...",
        "zh": "⏳ 正在后台创建分身中...",
    },
    "win_wizard_status_success": {
        "en": "🎉 Successfully created clone at {dest}!",
        "zh": "🎉 分身创建成功！位于 {dest}",
    },
    "win_wizard_status_failed": {
        "en": "❌ Clone failed: {error}",
        "zh": "❌ 分身创建失败: {error}",
    },
    "win_wizard_btn_back": {
        "en": "◀ Back",
        "zh": "◀ 上一步",
    },
    "win_wizard_btn_next": {
        "en": "Next ▶",
        "zh": "下一步 ▶",
    },
    "win_wizard_btn_clone_now": {
        "en": "🚀 Clone Now",
        "zh": "🚀 立即创建",
    },
    "win_detail_title": {
        "en": "Clone Details: {name}",
        "zh": "分身详情: {name}",
    },
    "win_detail_source_app": {
        "en": "Source App: {source_app}",
        "zh": "源应用: {source_app}",
    },
    "win_detail_source_path": {
        "en": "Source Path: {path}",
        "zh": "源应用路径: {path}",
    },
    "win_detail_bundle_id": {
        "en": "Bundle ID: {bundle_id}",
        "zh": "Bundle ID: {bundle_id}",
    },
    "win_detail_new_bundle_id": {
        "en": "New Bundle ID: {new_bundle_id}",
        "zh": "分身 Bundle ID: {new_bundle_id}",
    },
    "win_detail_strategy": {
        "en": "Strategy: {strategy}",
        "zh": "克隆策略: {strategy}",
    },
    "win_detail_dest_path": {
        "en": "Destination: {dest_path}",
        "zh": "分身保存路径: {dest_path}",
    },
    "win_detail_data_dir": {
        "en": "Data Dir: {data_dir}",
        "zh": "数据存储目录: {data_dir}",
    },
    "win_detail_created_at": {
        "en": "Created At: {created_at}",
        "zh": "创建时间: {created_at}",
    },
    "win_detail_proxy": {
        "en": "Proxy: {proxy}",
        "zh": "代理配置: {proxy}",
    },
    "win_detail_section_basic": {
        "en": "Basic Information",
        "zh": "基本信息",
    },
    "win_detail_section_injected": {
        "en": "Injected Parameters & Environment",
        "zh": "注入与启动参数",
    },
    "win_detail_launch_args": {
        "en": "Launch Arguments",
        "zh": "启动参数",
    },
    "win_detail_env_vars": {
        "en": "Environment Variables",
        "zh": "环境变量",
    },
    "win_detail_exec_cmd": {
        "en": "Launch Command",
        "zh": "启动命令",
    },
    "win_detail_btn_copy_cmd": {
        "en": "Copy Command",
        "zh": "复制命令",
    },
    "win_detail_cmd_copied": {
        "en": "Copied!",
        "zh": "已复制！",
    },
    "win_detail_btn_copy_all": {
        "en": "Copy All Information",
        "zh": "复制全部信息",
    },
    "win_detail_all_copied": {
        "en": "Copied All!",
        "zh": "已复制全部！",
    },
    "win_detail_none": {
        "en": "(None)",
        "zh": "(无)",
    },
    "win_edit_title": {
        "en": "Edit Clone: {name}",
        "zh": "编辑分身: {name}",
    },
    "win_edit_notes_label": {
        "en": "Notes:",
        "zh": "备注:",
    },
    "win_edit_notes_placeholder": {
        "en": "e.g. account name, purpose, region",
        "zh": "如：账号名、用途、地区",
    },
    "win_edit_switch_proxy": {
        "en": "Enable Dedicated Proxy",
        "zh": "启用专属代理",
    },
    "win_edit_type_host_port": {
        "en": "Type/Host/Port:",
        "zh": "类型/地址/端口:",
    },
    "proxy_auth_enable": {
        "en": "Proxy Authentication (Username/Password)",
        "zh": "代理身份验证（用户名/密码）",
    },
    "proxy_auth_username": {
        "en": "Username:",
        "zh": "用户名:",
    },
    "proxy_auth_password": {
        "en": "Password:",
        "zh": "密码:",
    },
    "proxy_auth_password_hint": {
        "en": "Stored securely in macOS Keychain",
        "zh": "安全保存在 macOS 系统钥匙串中",
    },
    "win_recipe_new_title": {
        "en": "New Clone Recipe",
        "zh": "新建分身规则",
    },
    "win_recipe_edit_title": {
        "en": "Edit Recipe: {name}",
        "zh": "编辑规则: {name}",
    },
    "win_recipe_bundle_id": {
        "en": "Bundle ID:",
        "zh": "Bundle ID:",
    },
    "win_recipe_app_name": {
        "en": "App Name:",
        "zh": "应用名称:",
    },
    "win_recipe_strategy": {
        "en": "Strategy:",
        "zh": "克隆策略:",
    },
    "win_recipe_injection_strategy": {
        "en": "Injection Mode:",
        "zh": "注入模式:",
    },
    "win_recipe_sandbox": {
        "en": "Sandbox:",
        "zh": "沙盒处理:",
    },
    "win_recipe_strip_sandbox": {
        "en": "Strip Sandbox",
        "zh": "解除沙盒限制",
    },
    "win_recipe_proxy_heading": {
        "en": "Proxy Settings",
        "zh": "代理配置",
    },
    "win_recipe_enable_proxy": {
        "en": "Enable Proxy",
        "zh": "启用代理",
    },
    "btn_save_recipe": {
        "en": "Save Recipe",
        "zh": "保存规则",
    },
    "win_recipe_btn_advanced_expand": {
        "en": "▶ Advanced Parameters (Expert)",
        "zh": "▶ 高级参数 (专家设置)",
    },
    "win_recipe_btn_advanced_collapse": {
        "en": "▼ Collapse Advanced Parameters",
        "zh": "▼ 收起高级参数",
    },
    "win_recipe_advanced_warning": {
        "en": "⚠️ For expert customization only. Invalid configurations may prevent the app from launching.",
        "zh": "⚠️ 仅供高级定制，错误配置可能导致应用无法启动",
    },
    "win_recipe_app_type": {
        "en": "App Type:",
        "zh": "应用类型:",
    },
    "win_recipe_app_type_auto": {
        "en": "Auto / Unspecified",
        "zh": "自动探测 / 未指定",
    },
    "win_recipe_language": {
        "en": "Display Language:",
        "zh": "界面语言:",
    },
    "win_recipe_env_injection": {
        "en": "Environment Variables:",
        "zh": "环境变量注入:",
    },
    "win_recipe_env_hint": {
        "en": "One KEY=VALUE per line. Supports {{TWINSPACE_DATA_DIR}} macro.",
        "zh": "每行一条 KEY=VALUE，支持 {{TWINSPACE_DATA_DIR}} 宏。",
    },
    "win_recipe_launch_args": {
        "en": "Launch Arguments:",
        "zh": "启动参数:",
    },
    "win_recipe_launch_args_hint": {
        "en": "One argument per line (e.g. --user-data-dir={{TWINSPACE_DATA_DIR}}).",
        "zh": "每行一个启动参数（如 --user-data-dir={{TWINSPACE_DATA_DIR}}）。",
    },
    "win_recipe_symlink_whitelist": {
        "en": "Symlink Whitelist:",
        "zh": "软链接白名单:",
    },
    "win_recipe_symlink_hint": {
        "en": "One path per line.",
        "zh": "每行一个相对或绝对路径。",
    },
    "dialog_recipe_invalid_env_line": {
        "en": "Invalid environment variable: line {line_num} '{line}' must follow KEY=VALUE format.",
        "zh": "环境变量解析错误：第 {line_num} 行 '{line}' 格式无效，必须为 KEY=VALUE 格式。",
    },
    "settings_btn_check_update": {
        "en": "🔄 Check for Updates",
        "zh": "🔄 检查更新",
    },
    "update_checking": {
        "en": "Checking for updates...",
        "zh": "正在检查更新...",
    },
    "update_already_latest": {
        "en": "✓ Already up to date (v{ver})",
        "zh": "✓ 已是最新版本 (v{ver})",
    },
    "update_found": {
        "en": "New version v{ver} found, downloading...",
        "zh": "发现新版本 v{ver}，正在下载...",
    },
    "update_downloading": {
        "en": "Downloading... {pct}%",
        "zh": "正在下载... {pct}%",
    },
    "update_verifying": {
        "en": "Verifying package checksum...",
        "zh": "正在校验安装包...",
    },
    "update_installing": {
        "en": "Installing update...",
        "zh": "正在安装更新...",
    },
    "update_done_title": {
        "en": "Update Complete",
        "zh": "更新完成",
    },
    "update_done_msg": {
        "en": "TwinSpace has been updated to v{ver}. Click OK to quit, then relaunch manually.",
        "zh": "TwinSpace 已成功更新至 v{ver}。点击确定后将退出应用，请手动重新启动。",
    },
    "update_error_short": {
        "en": "❌ Update check failed",
        "zh": "❌ 检查更新失败",
    },
    "update_error_timeout": {
        "en": "❌ Check failed: Timeout",
        "zh": "❌ 检查更新失败: 网络超时",
    },
    "update_error_network": {
        "en": "❌ Check failed: Network error",
        "zh": "❌ 检查更新失败: 网络连接异常",
    },
    "update_error_http": {
        "en": "❌ Check failed: HTTP {code}",
        "zh": "❌ 检查更新失败: HTTP {code}",
    },
    "settings_btn_release_notes": {
        "en": "📄 Release Notes",
        "zh": "📄 更新日志 (Release Notes)",
    },
    "release_notes_window_title": {
        "en": "TwinSpace Release Notes",
        "zh": "TwinSpace 更新日志",
    },
    "release_notes_lang_label": {
        "en": "Language:",
        "zh": "语言版本:",
    },
    "release_notes_btn_open_external": {
        "en": "📂 Open in Editor",
        "zh": "📂 在外部打开",
    },
    "release_notes_btn_close": {
        "en": "Close",
        "zh": "关闭",
    },
    "release_notes_err_not_found": {
        "en": "Release notes file not found: {path}",
        "zh": "未找到更新日志文件: {path}",
    },
}


def normalize_lang_code(raw: str | None) -> str:
    """Normalize a raw language / locale string to one of the supported codes."""
    if not raw:
        return "en"
    cleaned = raw.strip().lower().replace("-", "_")
    if not cleaned:
        return "en"

    # Any Chinese variant maps to Simplified Chinese.
    if cleaned.startswith("zh") or "hant" in cleaned:
        return "zh"
    return "en"


def detect_system_language() -> str:
    """Detect the current macOS system language, config preference, or environment preferences.

    Returns:
        One of the supported language codes: 'en' or 'zh'.
    """
    # 1. Explicit user override via environment variable (highest priority)
    override = (os.environ.get("TWINSPACE_LANG") or os.environ.get("ATBCLONE_LANG", "")).strip()
    if override:
        return normalize_lang_code(override)

    # 2. Persisted user configuration in ~/TwinSpace/config.yaml
    cfg_lang = get_configured_language()
    if cfg_lang and cfg_lang != "auto":
        return normalize_lang_code(cfg_lang)

    # 2. macOS System Preferences via 'defaults read -g AppleLanguages'
    try:
        out = subprocess.check_output(
            ["defaults", "read", "-g", "AppleLanguages"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        langs = re.findall(r'"([^"]+)"|([a-zA-Z0-9_-]+)', out)
        first_lang = next((a or b for a, b in langs if (a or b) not in ("(", ")", "")), "")
        if first_lang:
            norm = normalize_lang_code(first_lang)
            if norm != "en" or first_lang.lower().startswith("en"):
                return norm
    except Exception:
        pass

    # 3. macOS AppleLocale
    try:
        out = subprocess.check_output(
            ["defaults", "read", "-g", "AppleLocale"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            norm = normalize_lang_code(out)
            if norm != "en" or out.lower().startswith("en"):
                return norm
    except Exception:
        pass

    # 4. Standard environment variables (LC_ALL, LC_MESSAGES, LANG)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "").strip()
        if val:
            norm = normalize_lang_code(val)
            if norm != "en" or val.lower().startswith("en"):
                return norm

    # Default fallback to English
    return "en"


def get_language() -> str:
    """Get currently active language."""
    global _current_lang
    if _current_lang is not None:
        return _current_lang

    # Prefer TWINSPACE_LANG; keep the pre-3.0 ATBCLONE_LANG name working.
    if "TWINSPACE_LANG" in os.environ or "ATBCLONE_LANG" in os.environ:
        override = (os.environ.get("TWINSPACE_LANG") or os.environ.get("ATBCLONE_LANG", "")).strip()
        if override:
            return normalize_lang_code(override)

    return detect_system_language()


def set_language(lang: str | None) -> None:
    """Explicitly set or reset the active language ('zh', 'en', or None for auto)."""
    global _current_lang
    if lang is None:
        _current_lang = None
    else:
        _current_lang = normalize_lang_code(lang)


def is_chinese() -> bool:
    """Check if the active language is Chinese."""
    return get_language() == "zh"


def t(key: str, **kwargs: Any) -> str:
    """Translate a message key to the current language with optional keyword formatting."""
    lang = get_language()
    norm_lang = normalize_lang_code(lang)
    msg_dict = MESSAGES.get(key)
    if not msg_dict:
        return key.format(**kwargs) if kwargs else key

    template = (
        msg_dict.get(norm_lang)
        or msg_dict.get("en")
        or msg_dict.get("zh")
        or key
    )
    if kwargs:
        fmt_kwargs = dict(kwargs)
        if "path" in kwargs and "dir" not in fmt_kwargs:
            fmt_kwargs["dir"] = kwargs["path"]
        if "dir" in kwargs and "path" not in fmt_kwargs:
            fmt_kwargs["path"] = kwargs["dir"]
        if "dest_path" in kwargs and "dest" not in fmt_kwargs:
            fmt_kwargs["dest"] = kwargs["dest_path"]
        if "dest" in kwargs and "dest_path" not in fmt_kwargs:
            fmt_kwargs["dest_path"] = kwargs["dest"]
        if "path" in kwargs and "dest" not in fmt_kwargs:
            fmt_kwargs["dest"] = kwargs["path"]
        if "dest" in kwargs and "path" not in fmt_kwargs:
            fmt_kwargs["path"] = kwargs["dest"]
        if "version" in kwargs and "ver" not in fmt_kwargs:
            fmt_kwargs["ver"] = kwargs["version"]
        if "ver" in kwargs and "version" not in fmt_kwargs:
            fmt_kwargs["version"] = kwargs["ver"]
        if "os_ver" in kwargs and "ver" not in fmt_kwargs:
            fmt_kwargs["ver"] = kwargs["os_ver"]
        if "ver" in kwargs and "os_ver" not in fmt_kwargs:
            fmt_kwargs["os_ver"] = kwargs["ver"]
        try:
            return template.format(**fmt_kwargs)
        except Exception:
            return template
    return template


def get_configured_language() -> str:
    """Get the persisted language code from user config, returns 'auto' if unset."""
    try:
        from twinspace.core.config import get_config_value
        val = get_config_value("language", "auto")
        return str(val).strip() if val else "auto"
    except Exception:
        return "auto"


def save_configured_language(lang: str) -> None:
    """Persist language code ('auto', 'zh', 'en', ...) to user config."""
    try:
        from twinspace.core.config import set_config_value
        set_config_value("language", lang)
    except Exception:
        pass
