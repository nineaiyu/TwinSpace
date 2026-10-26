"""Clone engines for creating soft (wrapper) and hard (physical) app clones."""

import os
import shlex
import struct
import textwrap
from pathlib import Path

from twinspace.core.clone_task import CloneTask
from twinspace.core.locale import build_language_wrapper_snippet
from twinspace.core.logger import get_logger
from twinspace.executor.runner import CloneError, Runner
from twinspace.validation import escape_double_quoted

logger = get_logger("core.engines")


def _escape_c_string(value: str) -> str:
    """Escape a string for safe embedding inside a C string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


class CloneEngine:
    """Base class providing shared helper methods for clone engines."""

    _cached_clang_cmd: str | None = None

    # Presence of any of these env vars opts a clone into the isolation hook.
    ISOLATION_ENV_KEYS = (
        "TWINSPACE_KEYCHAIN_PREFIX",
        "TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES",
        "TWINSPACE_BROWSER_APP_PATH",
        "TWINSPACE_BROWSER_FALLBACK_APP_PATH",
        "TWINSPACE_BROWSER_DATA_DIR",
        "TWINSPACE_OAUTH_SCHEMES",
        "TWINSPACE_SCHEME_ALLOW_REGISTRATION",
        "TWINSPACE_COCOA_HOME_HOOK",
        "TWINSPACE_DEVICE_UUID",
        "TWINSPACE_DEVICE_SERIAL",
        "TWINSPACE_DEVICE_SEED",
        "TWINSPACE_DEVICE_HOSTNAME",
    )

    @staticmethod
    def _resolve_template(value: str, task: CloneTask) -> str:
        """Expand TwinSpace path/identity placeholders in recipes, args and env values."""
        replacements = {
            "TWINSPACE_DATA_DIR": str(task.data_dir),
            "TWINSPACE_ENV_DIR": str(task.resolved_env_dir),
            "TWINSPACE_CLONE_NAME": task.clone_name,
            "TWINSPACE_BUNDLE_ID": task.new_bundle_id,
            "TWINSPACE_INSTANCE_NUMBER": task.instance_number,
            "TWINSPACE_KEYCHAIN_PREFIX": task.keychain_prefix,
            "TWINSPACE_DEVICE_UUID": task.device_uuid,
            "TWINSPACE_DEVICE_SERIAL": task.device_serial,
            "TWINSPACE_DEVICE_SEED": task.device_seed,
            "TWINSPACE_DEVICE_HOSTNAME": task.device_hostname,
            "TWINSPACE_DEST_PATH": str(task.dest_path),
            "TWINSPACE_APPS_DIR": str(task.dest_path.parent),
        }
        resolved = value.replace("{{ATB_", "{{TWINSPACE_")
        for key, replacement in replacements.items():
            resolved = resolved.replace("{{" + key + "}}", replacement)
        return resolved

    @classmethod
    def _resolve_env(cls, task: CloneTask) -> dict[str, str]:
        """Return environment_injection with every TwinSpace placeholder expanded."""
        resolved = {
            key: cls._resolve_template(value, task)
            for key, value in task.recipe.environment_injection.items()
        }
        # Keep pre-3.0 ATB_* recipe overrides working alongside the new names.
        for key, value in list(resolved.items()):
            if key.startswith("ATB_"):
                resolved.setdefault("TWINSPACE_" + key[4:], value)
        return resolved

    @classmethod
    def _needs_isolation_hook(cls, effective_env: dict[str, str]) -> bool:
        """Return True when the recipe requests keychain/browser/OAuth isolation."""
        return any(effective_env.get(key) for key in cls.ISOLATION_ENV_KEYS)

    @classmethod
    def _build_data_dirs_cmd(cls, task: CloneTask, effective_env: dict[str, str]) -> str:
        """Create the clone/environment roots and every env var that points inside them."""
        directories = {
            task.data_dir,
            task.resolved_env_dir,
            task.data_dir / "Home",
            task.data_dir / "Tmp",
            task.resolved_env_dir / "Browser",
        }
        roots = [task.data_dir, task.resolved_env_dir]
        for key, value in effective_env.items():
            if not value:
                continue
            if not ("DIR" in key or key.endswith("HOME") or key in ("HOME", "TMPDIR")):
                continue
            path = Path(value)
            if not path.is_absolute():
                continue
            if any(path == root or path.is_relative_to(root) for root in roots):
                directories.add(path)
        return "mkdir -p " + " ".join(
            shlex.quote(str(directory)) for directory in sorted(directories)
        )

    @classmethod
    def _resolve_clang_command(cls) -> str:
        """Resolve a working clang invocation that pairs the compiler with a compatible macOS SDK."""
        if cls._cached_clang_cmd is not None:
            return cls._cached_clang_cmd

        import subprocess
        candidates = [
            "xcrun --sdk macosx clang",
            "DEVELOPER_DIR=/Library/Developer/CommandLineTools xcrun --sdk macosx clang",
            "clang",
        ]
        test_c = "int main(void){return 0;}"
        for cmd in candidates:
            try:
                res = subprocess.run(
                    f'echo "{test_c}" | {cmd} -x c - -o /dev/null',
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    cls._cached_clang_cmd = cmd
                    logger.debug(f"Resolved working clang command: {cmd}")
                    return cmd
            except Exception:
                continue

        cls._cached_clang_cmd = "xcrun --sdk macosx clang"
        return cls._cached_clang_cmd

    @staticmethod
    def _build_language_env_and_args(task: CloneTask) -> tuple[str, list[str]]:
        """Generate shell exports and launch arguments for language/locale configuration."""
        lang = getattr(task, "language", None) or getattr(task.recipe, "language", "system")
        app_type = getattr(task.recipe, "app_type", None)
        if not app_type and hasattr(task, "source") and task.source and getattr(task.source, "path", None):
            from twinspace.core.app_prober import AppProber
            app_type = AppProber.detect_app_type(
                task.source.path,
                bundle_id=getattr(task.source, "bundle_id", ""),
            )
        return build_language_wrapper_snippet(lang, app_type=app_type or "cocoa")

    @staticmethod
    def _build_proxy_env(task: CloneTask) -> str:
        """Generate shell export statements for proxy environment variables if enabled."""
        proxy = task.recipe.proxy
        if not proxy.enabled:
            return ""

        username = proxy.username
        password = proxy.password
        if username and not password and getattr(task, "clone_name", None):
            try:
                from twinspace.core.keychain import get_clone_proxy_password
                stored_pass = get_clone_proxy_password(task.clone_name)
                if stored_pass:
                    password = stored_pass
            except Exception:
                pass

        auth = f"{username}:{password}@" if username else ""
        proxy_url = f"{proxy.type}://{auth}{proxy.host}:{proxy.port}"
        return textwrap.dedent(f"""
            export HTTP_PROXY="{proxy_url}"
            export HTTPS_PROXY="{proxy_url}"
            export http_proxy="$HTTP_PROXY"
            export https_proxy="$HTTPS_PROXY"
            export NO_PROXY="{proxy.no_proxy}"
            export no_proxy="$NO_PROXY"
        """).strip()

    @classmethod
    def _get_validated_launch_args(cls, task: CloneTask) -> list[str]:
        """Validate launch_args against app_type and executable binary strings, pruning unsupported args."""
        from twinspace.core.argument_prober import LaunchArgumentValidator
        app_type = getattr(task.recipe, "app_type", None)
        if not app_type and hasattr(task, "source") and task.source and getattr(task.source, "path", None):
            from twinspace.core.app_prober import AppProber
            app_type = AppProber.detect_app_type(
                task.source.path,
                bundle_id=getattr(task.source, "bundle_id", ""),
            )
        exe_path = getattr(task.source, "executable", None) or task.source.path
        valid_args, _ = LaunchArgumentValidator.validate_and_filter(
            exe_path,
            task.recipe.launch_args,
            app_type=app_type or "generic",
        )
        return valid_args

    @staticmethod
    def _build_icon_cmd(task: CloneTask, dst_resources: str, dst_plist: str) -> str:
        """Install a standalone icon before signing, even for asset-catalog apps."""
        if task.icon_path is None:
            return ""
        custom_icon = shlex.quote(str(task.icon_path))
        return (
            f"mkdir -p {dst_resources}\n"
            f"cp {custom_icon} {dst_resources}/TwinSpaceIcon.icns\n"
            f'/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile TwinSpaceIcon.icns" {dst_plist} 2>/dev/null || '
            f'/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string TwinSpaceIcon.icns" {dst_plist}\n'
            f'/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" {dst_plist} 2>/dev/null || true\n'
        )

    @staticmethod
    def _build_display_name_cmd(effective_display_name: str, dst_plist: str, dst_resources: str) -> str:
        """Return a shell snippet that applies display name to Info.plist and removes localized overrides."""
        name_escaped = escape_double_quoted(effective_display_name)
        return textwrap.dedent(f"""
            /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName {name_escaped}" {dst_plist} 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string {name_escaped}" {dst_plist}
            /usr/libexec/PlistBuddy -c "Delete :LSHasLocalizedDisplayName" {dst_plist} 2>/dev/null || true
            if [ -d {dst_resources} ]; then
                find {dst_resources} -name "InfoPlist.strings" -type f -print0 2>/dev/null | while IFS= read -r -d '' str_file; do
                    /usr/libexec/PlistBuddy -c "Delete :CFBundleDisplayName" "$str_file" 2>/dev/null || true
                    /usr/libexec/PlistBuddy -c "Delete :CFBundleName" "$str_file" 2>/dev/null || true
                    /usr/libexec/PlistBuddy -c "Delete :CFBundleGetInfoString" "$str_file" 2>/dev/null || true
                done
            fi
        """).strip()

    @classmethod
    def _combine_launch_args(cls, valid_launch_args: list[str], lang_args: list[str], task: CloneTask) -> list[str]:
        """Combine recipe launch args with language args, deduplicating conflicting language flags."""
        args_list: list[str] = []
        lang_prefixes: set[str] = set()
        for larg in lang_args:
            if larg.startswith("--lang="):
                lang_prefixes.add("--lang=")
            elif larg in ("-AppleLanguages", "-AppleLocale"):
                lang_prefixes.add(larg)

        for arg in valid_launch_args:
            if any(arg.startswith(k) for k in lang_prefixes if k.startswith("--")):
                continue
            if arg in ("-AppleLanguages", "-AppleLocale"):
                continue
            args_list.append(cls._resolve_template(arg, task))

        for larg in lang_args:
            args_list.append(larg)

        return args_list

    @staticmethod
    def _build_lsregister_cmd(dst_app: str) -> str:
        """Return shell snippet to register the app bundle with LaunchServices."""
        return f"/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f {dst_app} 2>/dev/null || true"

    @classmethod
    def _build_codex_init_cmd(cls, task: CloneTask) -> str:
        """Return shell snippet to initialize clean CODEX_HOME directory at clone creation time."""
        if "CODEX_HOME" not in task.recipe.environment_injection:
            return ""
        target_path = cls._resolve_template(
            task.recipe.environment_injection["CODEX_HOME"], task
        )
        target_quoted = shlex.quote(target_path)
        return textwrap.dedent(f"""\
            mkdir -p {target_quoted}
        """).strip() + "\n"

    @classmethod
    def _build_gemini_init_cmd(cls, task: CloneTask) -> str:
        """Return shell snippet to initialize GEMINI_HOME from ~/.gemini at clone creation time."""
        target_val = (
            task.recipe.environment_injection.get("GEMINI_HOME")
            or task.recipe.environment_injection.get("ANTIGRAVITY_HOME")
            or task.recipe.environment_injection.get("GEMINI_CONFIG_DIR")
        )
        if not target_val:
            return ""
        target_path = cls._resolve_template(target_val, task)
        target_quoted = shlex.quote(target_path)
        return textwrap.dedent(f"""\
            if [ -d "$HOME/.gemini" ] && [ ! -d {target_quoted} ]; then
                mkdir -p {target_quoted}
                cp -R "$HOME/.gemini/." {target_quoted}/ 2>/dev/null || true
            fi
        """).strip() + "\n"

    @classmethod
    def _build_claude_init_cmd(cls, task: CloneTask) -> str:
        """Return shell snippet to initialize CLAUDE_CONFIG_DIR from ~/.claude at clone creation time."""
        if "CLAUDE_CONFIG_DIR" not in task.recipe.environment_injection:
            return ""
        target_path = cls._resolve_template(
            task.recipe.environment_injection["CLAUDE_CONFIG_DIR"], task
        )
        target_quoted = shlex.quote(target_path)
        return textwrap.dedent(f"""\
            if [ -d "$HOME/.claude" ] && [ ! -d {target_quoted} ]; then
                mkdir -p {target_quoted}
                cp -R "$HOME/.claude/." {target_quoted}/ 2>/dev/null || true
            fi
            if [ -f "$HOME/.claude.json" ] && [ ! -f {target_quoted}/.claude.json ]; then
                mkdir -p {target_quoted}
                cp "$HOME/.claude.json" {target_quoted}/.claude.json 2>/dev/null || true
            fi
        """).strip() + "\n"

    @staticmethod
    def _build_symlink_whitelist_snippet(task: CloneTask) -> str:
        """Return a shell snippet that creates symlinks for items in symlink_whitelist."""
        whitelist = getattr(task.recipe, "symlink_whitelist", [])
        if not whitelist:
            return ""
        data_dir_quoted = shlex.quote(str(task.data_dir))
        home_quoted = shlex.quote(str(task.data_dir / "Home"))
        lines = []
        for item in whitelist:
            item_clean = item.strip().strip("/")
            if not item_clean:
                continue
            item_quoted = shlex.quote(item_clean)
            lines.append(
                f'if [ -d {data_dir_quoted} ]; then\n'
                f'    mkdir -p {home_quoted}\n'
                f'    if [ ! -e {home_quoted}/{item_quoted} ] && [ -e "$HOME"/{item_quoted} ]; then\n'
                f'        mkdir -p "$(dirname {home_quoted}/{item_quoted})"\n'
                f'        ln -s "$HOME"/{item_quoted} {home_quoted}/{item_quoted} 2>/dev/null || true\n'
                f'    fi\n'
                f'fi'
            )
        return "\n".join(lines)

    @staticmethod
    def _build_preference_seeding_snippet(task: CloneTask) -> str:
        """Return a shell snippet that seeds initial preferences from the original app into the clone's HOME."""
        if not getattr(task.recipe, "seed_preferences", True):
            return ""
        orig_bundle_id = (
            getattr(task.source, "bundle_id", "")
            if hasattr(task, "source") and task.source
            else getattr(task.recipe, "bundle_id", "")
        )
        new_bundle_id = getattr(task, "new_bundle_id", "") or orig_bundle_id
        if not orig_bundle_id:
            return ""
        orig_quoted = shlex.quote(orig_bundle_id)
        data_dir_quoted = shlex.quote(str(task.data_dir))
        home_dir = task.data_dir / "Home"
        prefs_dir_quoted = shlex.quote(str(home_dir / "Library" / "Preferences"))
        tmp_dir_quoted = shlex.quote(str(task.data_dir / "Tmp"))
        global_prefs_dst = shlex.quote(str(home_dir / "Library" / "Preferences" / ".GlobalPreferences.plist"))
        cf_text_dst = shlex.quote(str(home_dir / ".CFUserTextEncoding"))
        orig_prefs_dst = shlex.quote(str(home_dir / "Library" / "Preferences" / f"{orig_bundle_id}.plist"))
        new_prefs_dst = shlex.quote(str(home_dir / "Library" / "Preferences" / f"{new_bundle_id}.plist"))
        lines = [
            f'if [ -d {data_dir_quoted} ]; then',
            f'    mkdir -p {prefs_dir_quoted} {tmp_dir_quoted} 2>/dev/null || true',
            f'    if [ ! -f {global_prefs_dst} ] && [ -f "$HOME/Library/Preferences/.GlobalPreferences.plist" ]; then',
            f'        cp "$HOME/Library/Preferences/.GlobalPreferences.plist" {global_prefs_dst} 2>/dev/null || true',
            '    fi',
            f'    if [ ! -f {cf_text_dst} ] && [ -f "$HOME/.CFUserTextEncoding" ]; then',
            f'        cp "$HOME/.CFUserTextEncoding" {cf_text_dst} 2>/dev/null || true',
            '    fi',
            f'    _ORIG_PLIST="$HOME/Library/Preferences/{orig_quoted}.plist"',
            f'    _CONTAINER_PLIST="$HOME/Library/Containers/{orig_quoted}/Data/Library/Preferences/{orig_quoted}.plist"',
            f'    if [ ! -f {orig_prefs_dst} ]; then',
            '        if [ -f "$_ORIG_PLIST" ]; then',
            f'            cp "$_ORIG_PLIST" {orig_prefs_dst} 2>/dev/null || true',
            '        elif [ -f "$_CONTAINER_PLIST" ]; then',
            f'            cp "$_CONTAINER_PLIST" {orig_prefs_dst} 2>/dev/null || true',
            '        fi',
            '    fi',
        ]
        if orig_bundle_id != new_bundle_id:
            lines.extend([
                f'    if [ ! -f {new_prefs_dst} ]; then',
                '        if [ -f "$_ORIG_PLIST" ]; then',
                f'            cp "$_ORIG_PLIST" {new_prefs_dst} 2>/dev/null || true',
                '        elif [ -f "$_CONTAINER_PLIST" ]; then',
                f'            cp "$_CONTAINER_PLIST" {new_prefs_dst} 2>/dev/null || true',
                '        fi',
                '    fi',
            ])
        lines.append("fi")
        return "\n".join(lines)

    @classmethod
    def _build_c_launcher_compile_cmd(
        cls,
        dst_wrapper: str,
        target_bin_statement: str,
        effective_env: dict[str, str],
        proxy_env: str,
        lang_env: str,
        args_list: list[str],
        data_dir: Path,
        hook_dylib_rel_path: str = "",
        extra_hook_dylib_rel_paths: list[str] | None = None,
    ) -> str:
        """Return a shell snippet that uses clang to compile a native Mach-O C launcher."""
        setenv_c_lines = [
            '    const char *orig_home = getenv("HOME");',
            '    if (orig_home && !getenv("REAL_USER_HOME")) {',
            '        setenv("REAL_USER_HOME", orig_home, 1);',
            '    }',
            '    /* A parent shell exporting this would turn Electron into plain Node. */',
            '    unsetenv("ELECTRON_RUN_AS_NODE");',
            '    /* VS Code-derived apps must not inherit another instance portable mode. */',
            '    unsetenv("VSCODE_PORTABLE");',
            '    unsetenv("VSCODE_APPDATA");',
            '    unsetenv("VSCODE_DEV");',
            '    unsetenv("VSCODE_PID");',
            '    unsetenv("VSCODE_IPC_HOOK");',
            '    unsetenv("VSCODE_IPC_HOOK_CLI");',
        ]
        for k, v in effective_env.items():
            val = v.replace("{{TWINSPACE_DATA_DIR}}", str(data_dir))
            k_esc = k.replace('"', '\\"')
            v_esc = val.replace('\\', '\\\\').replace('"', '\\"')
            setenv_c_lines.append(f'    setenv("{k_esc}", "{v_esc}", 1);')

        if proxy_env:
            proxy_map: dict[str, str] = {}
            for line in proxy_env.splitlines():
                if line.startswith("export "):
                    kv = line[7:]
                    if "=" in kv:
                        pk, pv = kv.split("=", 1)
                        pv_clean = pv.strip("'\"")
                        if pv_clean.startswith("$") and pv_clean[1:] in proxy_map:
                            pv_clean = proxy_map[pv_clean[1:]]
                        proxy_map[pk] = pv_clean
                        pk_esc = pk.replace('"', '\\"')
                        pv_esc = pv_clean.replace('\\', '\\\\').replace('"', '\\"')
                        setenv_c_lines.append(f'    setenv("{pk_esc}", "{pv_esc}", 1);')

        if lang_env:
            for line in lang_env.splitlines():
                if line.startswith("export "):
                    kv = line[7:]
                    if "=" in kv:
                        lk, lv = kv.split("=", 1)
                        lv_clean = lv.strip("'\"")
                        lk_esc = lk.replace('"', '\\"')
                        lv_esc = lv_clean.replace('\\', '\\\\').replace('"', '\\"')
                        setenv_c_lines.append(f'    setenv("{lk_esc}", "{lv_esc}", 1);')

        setenv_block = "\n".join(setenv_c_lines)

        if args_list:
            escaped_args = ", ".join(
                f'"{arg.replace("\\", "\\\\").replace("\"", "\\\"")}"'
                for arg in args_list
            )
            args_block = f"""    char *hardcoded_args[] = {{{escaped_args}}};
    int hardcoded_count = {len(args_list)};
    char **new_argv = malloc((argc + hardcoded_count + 1) * sizeof(char *));
    if (!new_argv) return 1;
    new_argv[0] = argv[0];
    for (int i = 0; i < hardcoded_count; i++) {{
        new_argv[i + 1] = hardcoded_args[i];
    }}
    for (int i = 1; i < argc; i++) {{
        new_argv[hardcoded_count + i] = argv[i];
    }}
    new_argv[argc + hardcoded_count] = NULL;"""
            exec_argv = "new_argv"
        else:
            args_block = "    char **new_argv = argv;"
            exec_argv = "new_argv"

        hook_paths = []
        if hook_dylib_rel_path:
            hook_paths.append(hook_dylib_rel_path)
        hook_paths.extend(extra_hook_dylib_rel_paths or [])

        hook_block = ""
        if hook_paths:
            hook_array = ", ".join(
                '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'
                for path in hook_paths
            )
            hook_block = f"""    {{
        char hook_exe_buf[PATH_MAX];
        uint32_t hook_exe_size = sizeof(hook_exe_buf);
        if (_NSGetExecutablePath(hook_exe_buf, &hook_exe_size) != 0) return 1;
        char *hook_dir = dirname(hook_exe_buf);
        const char *hook_rels[] = {{{hook_array}}};
        int hook_count = {len(hook_paths)};
        char hook_joined[PATH_MAX * 4];
        hook_joined[0] = '\\0';
        for (int i = 0; i < hook_count; i++) {{
            if (i > 0) strncat(hook_joined, ":", sizeof(hook_joined) - strlen(hook_joined) - 1);
            strncat(hook_joined, hook_dir, sizeof(hook_joined) - strlen(hook_joined) - 1);
            strncat(hook_joined, "/", sizeof(hook_joined) - strlen(hook_joined) - 1);
            strncat(hook_joined, hook_rels[i], sizeof(hook_joined) - strlen(hook_joined) - 1);
        }}
        const char *existing_dyld = getenv("DYLD_INSERT_LIBRARIES");
        char hook_path[PATH_MAX * 6];
        if (existing_dyld && strlen(existing_dyld) > 0) {{
            snprintf(hook_path, sizeof(hook_path), "%s:%s", existing_dyld, hook_joined);
        }} else {{
            snprintf(hook_path, sizeof(hook_path), "%s", hook_joined);
        }}
        setenv("DYLD_INSERT_LIBRARIES", hook_path, 1);
    }}
"""

        c_source = f"""#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>

int main(int argc, char *argv[]) {{
{target_bin_statement}

{setenv_block}

{args_block}
{hook_block}
    execv(real_bin, {exec_argv});
    perror("execv failed");
    return 1;
}}
"""
        clang_cmd = cls._resolve_clang_command()
        return f"""{clang_cmd} -O2 -x c - -o {dst_wrapper} << 'LAUNCHER_C_EOF'
{c_source}LAUNCHER_C_EOF
chmod +x {dst_wrapper}
"""

    @classmethod
    def _build_dylib_env_cmd(
        cls,
        dst_frameworks: str,
        effective_env: dict[str, str],
        proxy_env: str,
        lang_env: str,
        data_dir: Path,
        bin_orig: str,
    ) -> str:
        """Compile a lightweight environment injection dylib and insert LC_LOAD_DYLIB into bin_orig."""
        # Clean quotes around paths before inserting into python script template
        clean_bin = bin_orig.strip("'\"")

        setenv_c_lines = [
            '    const char *orig_home = getenv("HOME");',
            '    if (orig_home && !getenv("REAL_USER_HOME")) {',
            '        setenv("REAL_USER_HOME", orig_home, 1);',
            '    }',
            '    /* A parent shell exporting this would turn Electron into plain Node. */',
            '    unsetenv("ELECTRON_RUN_AS_NODE");',
            '    /* VS Code-derived apps must not inherit another instance portable mode. */',
            '    unsetenv("VSCODE_PORTABLE");',
            '    unsetenv("VSCODE_APPDATA");',
            '    unsetenv("VSCODE_DEV");',
            '    unsetenv("VSCODE_PID");',
            '    unsetenv("VSCODE_IPC_HOOK");',
            '    unsetenv("VSCODE_IPC_HOOK_CLI");',
        ]
        for k, v in effective_env.items():
            val = v.replace("{{TWINSPACE_DATA_DIR}}", str(data_dir))
            k_esc = k.replace('"', '\\"')
            v_esc = val.replace('\\', '\\\\').replace('"', '\\"')
            setenv_c_lines.append(f'    setenv("{k_esc}", "{v_esc}", 1);')

        if proxy_env:
            proxy_map: dict[str, str] = {}
            for line in proxy_env.splitlines():
                if line.startswith("export "):
                    kv = line[7:]
                    if "=" in kv:
                        pk, pv = kv.split("=", 1)
                        pv_clean = pv.strip("'\"")
                        if pv_clean.startswith("$") and pv_clean[1:] in proxy_map:
                            pv_clean = proxy_map[pv_clean[1:]]
                        proxy_map[pk] = pv_clean
                        pk_esc = pk.replace('"', '\\"')
                        pv_esc = pv_clean.replace('\\', '\\\\').replace('"', '\\"')
                        setenv_c_lines.append(f'    setenv("{pk_esc}", "{pv_esc}", 1);')

        if lang_env:
            for line in lang_env.splitlines():
                if line.startswith("export "):
                    kv = line[7:]
                    if "=" in kv:
                        lk, lv = kv.split("=", 1)
                        lv_clean = lv.strip("'\"")
                        lk_esc = lk.replace('"', '\\"')
                        lv_esc = lv_clean.replace('\\', '\\\\').replace('"', '\\"')
                        setenv_c_lines.append(f'    setenv("{lk_esc}", "{lv_esc}", 1);')

        setenv_block = "\n".join(setenv_c_lines)

        c_source = f"""#include <stdlib.h>

__attribute__((constructor))
static void twinspace_env_init(void) {{
{setenv_block}
}}
"""
        py_insert_dylib = f"""TWINSPACE_INJECT_BIN={shlex.quote(clean_bin)} python3 -c "
import os
import struct
import sys

def insert_dylib(macho_path, dylib_path):
    with open(macho_path, 'rb') as fp:
        data = bytearray(fp.read())
    m_magic = struct.unpack_from('<I', data, 0)[0]
    is_fat = (m_magic in (0xcafebabe, 0xbebafeca))
    headers = []
    if is_fat:
        nfat = struct.unpack_from('>I', data, 4)[0]
        for i in range(nfat):
            arch_offset = struct.unpack_from('>I', data, 8 + i * 20 + 8)[0]
            headers.append(arch_offset)
    else:
        headers.append(0)

    for offset in headers:
        magic = struct.unpack_from('<I', data, offset)[0]
        if magic != 0xfeedfacf:
            continue
        m_magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from('<IIIIIIII', data, offset)
        path_bytes = dylib_path.encode('utf-8') + b'\\0'
        aligned_path_len = (len(path_bytes) + 7) & ~7
        cmdsize = 24 + aligned_path_len
        load_cmd = struct.pack('<IIIIII', 0x0c, cmdsize, 24, 0, 0, 0) + path_bytes + b'\\0' * (aligned_path_len - len(path_bytes))

        # Check existing commands to avoid duplicates
        existing_cmds = set()
        cmd_offset = offset + 32
        for _ in range(ncmds):
            cmd, csize = struct.unpack_from('<II', data, cmd_offset)
            if cmd in (0x0c, 0x8000001c):
                stroff = struct.unpack_from('<I', data, cmd_offset + 8)[0]
                str_end = data.find(b'\\0', cmd_offset + stroff)
                existing_cmds.add(bytes(data[cmd_offset + stroff:str_end]))
            cmd_offset += csize

        end_of_cmds = offset + 32 + sizeofcmds
        if dylib_path.encode('utf-8') in existing_cmds:
            continue
        data[end_of_cmds:end_of_cmds+cmdsize] = load_cmd
        ncmds += 1
        sizeofcmds += cmdsize
        data[offset:offset+32] = struct.pack('<IIIIIIII', m_magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved)
    with open(macho_path, 'wb') as fp:
        fp.write(data)

raw_bin = os.environ['TWINSPACE_INJECT_BIN']
insert_dylib(raw_bin, '@executable_path/../Frameworks/libtwinspace_env.dylib')
"
"""
        clang_cmd = cls._resolve_clang_command()
        return f"""mkdir -p {dst_frameworks}
{clang_cmd} -dynamiclib -O2 -arch arm64 -arch x86_64 -install_name @executable_path/../Frameworks/libtwinspace_env.dylib -o {dst_frameworks}/libtwinspace_env.dylib -x c - << 'TWINSPACE_DYLIB_EOF'
{c_source}TWINSPACE_DYLIB_EOF
chmod +x {dst_frameworks}/libtwinspace_env.dylib
if [ -d {dst_frameworks}/ld ]; then
    ln -sf ../libtwinspace_env.dylib {dst_frameworks}/ld/libtwinspace_env.dylib 2>/dev/null || cp -f {dst_frameworks}/libtwinspace_env.dylib {dst_frameworks}/ld/libtwinspace_env.dylib 2>/dev/null || true
fi
{py_insert_dylib}"""

    @classmethod
    def _build_isolation_hook_cmd(cls, task: CloneTask) -> str:
        """Compile libtwinspace_isolation.dylib for keychain, browser and OAuth isolation."""
        dst_frameworks = shlex.quote(str(task.dest_path / "Contents" / "Frameworks"))
        source = textwrap.dedent(r'''
            #import <AppKit/AppKit.h>
            #import <Foundation/Foundation.h>
            #import <Security/Security.h>
            #import <CoreServices/CoreServices.h>
            #import <IOKit/IOKitLib.h>
            #import <DiskArbitration/DiskArbitration.h>
            #import <CommonCrypto/CommonDigest.h>
            #import <ifaddrs.h>
            #import <net/if_dl.h>
            #import <sys/socket.h>
            #import <objc/runtime.h>
            #import <unistd.h>
            #import <pwd.h>
            #import <stdlib.h>
            #import <string.h>
            #import <stdio.h>
            #import <stdarg.h>

            #define TWINSPACE_DYLD_INTERPOSE(_replacement,_replacee) \
                __attribute__((used)) static struct { const void *replacement; const void *replacee; } \
                _interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = \
                { (const void *)(unsigned long)&_replacement, (const void *)(unsigned long)&_replacee };

            static NSString *TwinSpaceEnv(NSString *key) {
                const char *value = getenv(key.UTF8String);
                if (!value || !value[0]) return nil;
                return [NSString stringWithUTF8String:value];
            }

            static void TwinSpaceLog(NSString *format, ...) {
                const char *path = getenv("TWINSPACE_ISOLATION_LOG");
                if (!path || !path[0]) return;
                va_list args;
                va_start(args, format);
                NSString *message = [[NSString alloc] initWithFormat:format arguments:args];
                va_end(args);
                FILE *fp = fopen(path, "a");
                if (fp) {
                    fprintf(fp, "[%d] %s\n", getpid(), message.UTF8String);
                    fclose(fp);
                }
            }

            static BOOL TwinSpaceHomeHookEnabled(void) {
                const char *enabled = getenv("TWINSPACE_COCOA_HOME_HOOK");
                return enabled && enabled[0] && strcmp(enabled, "0") != 0;
            }

            static NSString *TwinSpaceHomeDirectory(void) {
                if (!TwinSpaceHomeHookEnabled()) return NSHomeDirectory();
                const char *custom = getenv("HOME");
                if (custom && custom[0]) return [NSString stringWithUTF8String:custom];
                return NSHomeDirectory();
            }

            static NSString *TwinSpaceHomeDirectoryForUser(NSString *userName) {
                if (!TwinSpaceHomeHookEnabled()) return NSHomeDirectoryForUser(userName);
                const char *custom = getenv("HOME");
                if (custom && custom[0]) return [NSString stringWithUTF8String:custom];
                return NSHomeDirectoryForUser(userName);
            }

            static NSString *TwinSpaceTemporaryDirectory(void) {
                if (!TwinSpaceHomeHookEnabled()) return NSTemporaryDirectory();
                const char *custom = getenv("TMPDIR");
                if (custom && custom[0]) {
                    NSString *path = [NSString stringWithUTF8String:custom];
                    if (![path hasSuffix:@"/"]) path = [path stringByAppendingString:@"/"];
                    [[NSFileManager defaultManager] createDirectoryAtPath:path
                        withIntermediateDirectories:YES attributes:nil error:nil];
                    return path;
                }
                return NSTemporaryDirectory();
            }

            static NSArray<NSString *> *TwinSpaceSearchPathForDirectoriesInDomains(
                NSSearchPathDirectory directory,
                NSSearchPathDomainMask domainMask,
                BOOL expandTilde) {
                if (!TwinSpaceHomeHookEnabled()) {
                    return NSSearchPathForDirectoriesInDomains(directory, domainMask, expandTilde);
                }
                const char *custom_home = getenv("HOME");
                if (custom_home && custom_home[0] && (domainMask & NSUserDomainMask)) {
                    NSString *home = [NSString stringWithUTF8String:custom_home];
                    NSString *sub = nil;
                    switch (directory) {
                        case NSApplicationSupportDirectory: sub = @"Library/Application Support"; break;
                        case NSCachesDirectory: sub = @"Library/Caches"; break;
                        case NSLibraryDirectory: sub = @"Library"; break;
                        case NSDocumentDirectory: sub = @"Documents"; break;
                        default: break;
                    }
                    if (sub) {
                        NSString *full = [home stringByAppendingPathComponent:sub];
                        [[NSFileManager defaultManager] createDirectoryAtPath:full
                            withIntermediateDirectories:YES attributes:nil error:nil];
                        return @[full];
                    }
                }
                return NSSearchPathForDirectoriesInDomains(directory, domainMask, expandTilde);
            }

            static struct passwd *TwinSpaceGetpwuid(uid_t uid) {
                struct passwd *pw = getpwuid(uid);
                if (pw && TwinSpaceHomeHookEnabled()) {
                    const char *custom_home = getenv("HOME");
                    if (custom_home && custom_home[0]) {
                        __thread static struct passwd fake_pw;
                        fake_pw = *pw;
                        fake_pw.pw_dir = (char *)custom_home;
                        return &fake_pw;
                    }
                }
                return pw;
            }

            static int TwinSpaceGetpwuidR(uid_t uid, struct passwd *pwd, char *buffer,
                                    size_t bufsize, struct passwd **result) {
                int ret = getpwuid_r(uid, pwd, buffer, bufsize, result);
                if (ret == 0 && result && *result && TwinSpaceHomeHookEnabled()) {
                    const char *custom_home = getenv("HOME");
                    if (custom_home && custom_home[0]) pwd->pw_dir = (char *)custom_home;
                }
                return ret;
            }

            static size_t TwinSpaceConfstr(int name, char *buf, size_t len) {
                if (TwinSpaceHomeHookEnabled() &&
                    (name == _CS_DARWIN_USER_TEMP_DIR || name == _CS_DARWIN_USER_CACHE_DIR)) {
                    const char *custom_tmp = getenv("TMPDIR");
                    if (custom_tmp && custom_tmp[0]) {
                        size_t needed = strlen(custom_tmp) + 1;
                        if (buf && len > 0) {
                            strncpy(buf, custom_tmp, len);
                            buf[len - 1] = 0;
                        }
                        return needed;
                    }
                }
                return confstr(name, buf, len);
            }

            TWINSPACE_DYLD_INTERPOSE(TwinSpaceHomeDirectory, NSHomeDirectory)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceHomeDirectoryForUser, NSHomeDirectoryForUser)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceTemporaryDirectory, NSTemporaryDirectory)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSearchPathForDirectoriesInDomains, NSSearchPathForDirectoriesInDomains)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceGetpwuid, getpwuid)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceGetpwuidR, getpwuid_r)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceConfstr, confstr)

            // Platform identity: apps that fingerprint the host through IOKit
            // see the real machine UUID/serial, so every clone of the same app
            // looks like the same device. Recipes can opt into per-clone
            // values by setting TWINSPACE_DEVICE_UUID / TWINSPACE_DEVICE_SERIAL.

            static NSString *TwinSpaceDeviceUUID(void) {
                static NSString *value;
                static dispatch_once_t once;
                dispatch_once(&once, ^{ value = TwinSpaceEnv(@"TWINSPACE_DEVICE_UUID"); });
                return value;
            }

            static NSString *TwinSpaceDeviceSerial(void) {
                static NSString *value;
                static dispatch_once_t once;
                dispatch_once(&once, ^{ value = TwinSpaceEnv(@"TWINSPACE_DEVICE_SERIAL"); });
                return value;
            }

            static NSString *TwinSpacePlatformOverride(CFStringRef key) {
                if (!key) return nil;
                NSString *name = (__bridge NSString *)key;
                if ([name isEqualToString:@"IOPlatformUUID"]) return TwinSpaceDeviceUUID();
                if ([name isEqualToString:@"IOPlatformSerialNumber"]) return TwinSpaceDeviceSerial();
                return nil;
            }

            static CFTypeRef TwinSpaceIORegistryEntryCreateCFProperty(
                io_registry_entry_t entry,
                CFStringRef key,
                CFAllocatorRef allocator,
                IOOptionBits options) {
                NSString *override = TwinSpacePlatformOverride(key);
                if (override.length) {
                    TwinSpaceLog(@"platform property %@ -> %@", key, override);
                    return CFBridgingRetain(override);
                }
                return IORegistryEntryCreateCFProperty(entry, key, allocator, options);
            }

            static CFTypeRef TwinSpaceIORegistryEntrySearchCFProperty(
                io_registry_entry_t entry,
                const io_name_t plane,
                CFStringRef key,
                CFAllocatorRef allocator,
                IOOptionBits options) {
                NSString *override = TwinSpacePlatformOverride(key);
                if (override.length) return CFBridgingRetain(override);
                return IORegistryEntrySearchCFProperty(entry, plane, key, allocator, options);
            }

            TWINSPACE_DYLD_INTERPOSE(TwinSpaceIORegistryEntryCreateCFProperty, IORegistryEntryCreateCFProperty)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceIORegistryEntrySearchCFProperty, IORegistryEntrySearchCFProperty)

            // Additional hardware identity: disk UUIDs (DiskArbitration),
            // interface MAC addresses (getifaddrs) and the hostname. Every value
            // is derived from TWINSPACE_DEVICE_SEED plus the original, so each
            // clone keeps stable yet distinct identifiers for its disks and
            // network interfaces.

            static NSString *TwinSpaceDeviceSeed(void) {
                static NSString *value;
                static dispatch_once_t once;
                dispatch_once(&once, ^{ value = TwinSpaceEnv(@"TWINSPACE_DEVICE_SEED"); });
                return value;
            }

            static BOOL TwinSpaceSeedDigest(NSString *original,
                                            unsigned char out[CC_MD5_DIGEST_LENGTH]) {
                NSString *seed = TwinSpaceDeviceSeed();
                if (!seed.length || !original.length) return NO;
                NSString *input = [NSString stringWithFormat:@"%@|%@", seed, original];
                CC_MD5(input.UTF8String, (CC_LONG)strlen(input.UTF8String), out);
                return YES;
            }

            static CFUUIDRef TwinSpaceDerivedUUID(CFTypeRef value) {
                if (!value) return NULL;
                NSString *text = nil;
                CFTypeID type = CFGetTypeID(value);
                if (type == CFUUIDGetTypeID()) {
                    CFStringRef rendered = CFUUIDCreateString(kCFAllocatorDefault, (CFUUIDRef)value);
                    text = rendered ? (__bridge_transfer NSString *)rendered : nil;
                } else if (type == CFStringGetTypeID()) {
                    text = (__bridge NSString *)value;
                }
                if (!text.length) return NULL;
                unsigned char digest[CC_MD5_DIGEST_LENGTH];
                if (!TwinSpaceSeedDigest(text, digest)) return NULL;
                return CFUUIDCreateWithBytes(kCFAllocatorDefault,
                    digest[0], digest[1], digest[2], digest[3], digest[4], digest[5],
                    digest[6], digest[7], digest[8], digest[9], digest[10], digest[11],
                    digest[12], digest[13], digest[14], digest[15]);
            }

            static CFDataRef TwinSpaceDerivedGUIDData(CFDataRef data) {
                if (!data) return NULL;
                NSString *text = [(__bridge NSData *)data description];
                unsigned char digest[CC_MD5_DIGEST_LENGTH];
                if (!TwinSpaceSeedDigest(text, digest)) return NULL;
                return CFDataCreate(kCFAllocatorDefault, digest, CC_MD5_DIGEST_LENGTH);
            }

            static CFDictionaryRef TwinSpaceDADiskCopyDescription(DADiskRef disk) {
                CFDictionaryRef original = DADiskCopyDescription(disk);
                if (!original) return NULL;
                if (!TwinSpaceDeviceSeed().length) return original;
                NSMutableDictionary *dict = [(__bridge NSDictionary *)original mutableCopy];
                CFRelease(original);
                for (NSString *key in @[
                        (__bridge NSString *)kDADiskDescriptionMediaUUIDKey,
                        (__bridge NSString *)kDADiskDescriptionVolumeUUIDKey]) {
                    CFUUIDRef derived = TwinSpaceDerivedUUID((__bridge CFTypeRef)dict[key]);
                    if (derived) dict[key] = (__bridge_transfer id)derived;
                }
                NSString *guidKey = (__bridge NSString *)kDADiskDescriptionDeviceGUIDKey;
                CFDataRef derivedGUID = TwinSpaceDerivedGUIDData((__bridge CFDataRef)dict[guidKey]);
                if (derivedGUID) dict[guidKey] = (__bridge_transfer id)derivedGUID;
                return CFBridgingRetain(dict);
            }

            static int TwinSpaceGetifaddrs(struct ifaddrs **ifap) {
                int status = getifaddrs(ifap);
                if (status != 0 || !ifap || !*ifap || !TwinSpaceDeviceSeed().length) return status;
                for (struct ifaddrs *ifa = *ifap; ifa; ifa = ifa->ifa_next) {
                    if (!ifa->ifa_addr || ifa->ifa_addr->sa_family != AF_LINK) continue;
                    if (!ifa->ifa_name || strncmp(ifa->ifa_name, "lo", 2) == 0) continue;
                    struct sockaddr_dl *link = (struct sockaddr_dl *)ifa->ifa_addr;
                    if (link->sdl_alen != 6) continue;
                    unsigned char *mac = (unsigned char *)LLADDR(link);
                    NSString *material = [NSString stringWithFormat:
                        @"%s|%02x:%02x:%02x:%02x:%02x:%02x",
                        ifa->ifa_name, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]];
                    unsigned char digest[CC_MD5_DIGEST_LENGTH];
                    if (!TwinSpaceSeedDigest(material, digest)) continue;
                    memcpy(mac, digest, 6);
                    mac[0] = (unsigned char)((mac[0] & 0xFC) | 0x02);
                }
                return status;
            }

            static int TwinSpaceGethostname(char *name, size_t len) {
                NSString *override = TwinSpaceEnv(@"TWINSPACE_DEVICE_HOSTNAME");
                if (override.length && name && len > 0) {
                    const char *utf8 = override.UTF8String;
                    size_t count = strlen(utf8);
                    if (count >= len) count = len - 1;
                    memcpy(name, utf8, count);
                    name[count] = '\0';
                    return 0;
                }
                return gethostname(name, len);
            }

            TWINSPACE_DYLD_INTERPOSE(TwinSpaceDADiskCopyDescription, DADiskCopyDescription)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceGetifaddrs, getifaddrs)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceGethostname, gethostname)

            static NSString *TwinSpaceKeychainPrefix(void) {
                static NSString *prefix;
                static dispatch_once_t once;
                dispatch_once(&once, ^{ prefix = TwinSpaceEnv(@"TWINSPACE_KEYCHAIN_PREFIX"); });
                return prefix;
            }

            static NSSet<NSString *> *TwinSpaceKeychainExcludedServices(void) {
                static NSSet<NSString *> *services;
                static dispatch_once_t once;
                dispatch_once(&once, ^{
                    NSString *raw = TwinSpaceEnv(@"TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES");
                    NSMutableSet *set = [NSMutableSet set];
                    for (NSString *item in [raw componentsSeparatedByString:@","]) {
                        NSString *trimmed = [item stringByTrimmingCharactersInSet:
                            [NSCharacterSet whitespaceCharacterSet]];
                        if (trimmed.length) [set addObject:trimmed];
                    }
                    services = [set copy];
                });
                return services;
            }

            static BOOL TwinSpaceServiceIsExcluded(NSString *service) {
                for (NSString *pattern in TwinSpaceKeychainExcludedServices()) {
                    if ([pattern hasSuffix:@"*"]) {
                        NSString *prefix = [pattern substringToIndex:pattern.length - 1];
                        if ([service hasPrefix:prefix]) return YES;
                    } else if ([service isEqualToString:pattern]) {
                        return YES;
                    }
                }
                return NO;
            }

            static NSMutableDictionary *TwinSpaceNamespacedDictionary(CFDictionaryRef dictionary) {
                if (!dictionary) return nil;
                NSMutableDictionary *mutable = [(__bridge NSDictionary *)dictionary mutableCopy];
                NSString *prefix = TwinSpaceKeychainPrefix();
                if (!prefix.length) return mutable;
                NSString *classValue = mutable[(__bridge NSString *)kSecClass];
                if (![classValue isEqualToString:(__bridge NSString *)kSecClassGenericPassword] &&
                    ![classValue isEqualToString:(__bridge NSString *)kSecClassInternetPassword]) {
                    return mutable;
                }
                NSString *service = mutable[(__bridge NSString *)kSecAttrService];
                if (![service isKindOfClass:[NSString class]] || !service.length) return mutable;
                if ([service hasPrefix:prefix]) return mutable;
                if (TwinSpaceServiceIsExcluded(service)) return mutable;
                NSString *namespaced = [prefix stringByAppendingString:service];
                mutable[(__bridge NSString *)kSecAttrService] = namespaced;
                TwinSpaceLog(@"keychain service %@ -> %@", service, namespaced);
                return mutable;
            }

            // Calls made from this interposing image bind to the original symbols;
            // dyld deliberately does not rewrite them. Do NOT use dlsym(RTLD_NEXT)
            // here: dyld redirects that lookup back to these replacements.
            static OSStatus TwinSpaceSecItemAdd(CFDictionaryRef attributes, CFTypeRef *result) {
                NSMutableDictionary *dict = TwinSpaceNamespacedDictionary(attributes);
                return SecItemAdd(dict ? (__bridge CFDictionaryRef)dict : attributes, result);
            }

            static OSStatus TwinSpaceSecItemCopyMatching(CFDictionaryRef query, CFTypeRef *result) {
                NSMutableDictionary *dict = TwinSpaceNamespacedDictionary(query);
                return SecItemCopyMatching(dict ? (__bridge CFDictionaryRef)dict : query, result);
            }

            static OSStatus TwinSpaceSecItemUpdate(CFDictionaryRef query, CFDictionaryRef attributesToUpdate) {
                NSMutableDictionary *queryDict = TwinSpaceNamespacedDictionary(query);
                NSMutableDictionary *updateDict = TwinSpaceNamespacedDictionary(attributesToUpdate);
                return SecItemUpdate(
                    queryDict ? (__bridge CFDictionaryRef)queryDict : query,
                    updateDict ? (__bridge CFDictionaryRef)updateDict : attributesToUpdate);
            }

            static OSStatus TwinSpaceSecItemDelete(CFDictionaryRef query) {
                NSMutableDictionary *dict = TwinSpaceNamespacedDictionary(query);
                return SecItemDelete(dict ? (__bridge CFDictionaryRef)dict : query);
            }

            static char *TwinSpacePrefixedCString(const char *service, UInt32 length) {
                if (!service || length == 0) return NULL;
                NSString *prefix = TwinSpaceKeychainPrefix();
                if (!prefix.length) return NULL;
                NSString *original = [[NSString alloc] initWithBytes:service
                                                              length:length
                                                            encoding:NSUTF8StringEncoding];
                if (!original.length) return NULL;
                if ([original hasPrefix:prefix]) return NULL;
                if (TwinSpaceServiceIsExcluded(original)) return NULL;
                NSString *namespaced = [prefix stringByAppendingString:original];
                return strdup(namespaced.UTF8String);
            }

            static OSStatus TwinSpaceSecKeychainFindGenericPassword(
                CFTypeRef keychainOrArray,
                UInt32 serviceNameLength, const char *serviceName,
                UInt32 accountNameLength, const char *accountName,
                UInt32 *passwordLength, void **passwordData,
                SecKeychainItemRef *itemRef) {
                char *prefixed = TwinSpacePrefixedCString(serviceName, serviceNameLength);
                OSStatus status = SecKeychainFindGenericPassword(
                    keychainOrArray,
                    prefixed ? (UInt32)strlen(prefixed) : serviceNameLength,
                    prefixed ?: serviceName,
                    accountNameLength, accountName,
                    passwordLength, passwordData, itemRef);
                free(prefixed);
                return status;
            }

            static OSStatus TwinSpaceSecKeychainAddGenericPassword(
                SecKeychainRef keychain,
                UInt32 serviceNameLength, const char *serviceName,
                UInt32 accountNameLength, const char *accountName,
                UInt32 passwordLength, const void *passwordData,
                SecKeychainItemRef *itemRef) {
                char *prefixed = TwinSpacePrefixedCString(serviceName, serviceNameLength);
                OSStatus status = SecKeychainAddGenericPassword(
                    keychain,
                    prefixed ? (UInt32)strlen(prefixed) : serviceNameLength,
                    prefixed ?: serviceName,
                    accountNameLength, accountName,
                    passwordLength, passwordData, itemRef);
                free(prefixed);
                return status;
            }

            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecItemAdd, SecItemAdd)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecItemCopyMatching, SecItemCopyMatching)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecItemUpdate, SecItemUpdate)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecItemDelete, SecItemDelete)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecKeychainFindGenericPassword, SecKeychainFindGenericPassword)
            TWINSPACE_DYLD_INTERPOSE(TwinSpaceSecKeychainAddGenericPassword, SecKeychainAddGenericPassword)

            static NSArray<NSString *> *TwinSpaceEnvList(NSString *key) {
                NSString *raw = TwinSpaceEnv(key);
                NSMutableArray *items = [NSMutableArray array];
                for (NSString *item in [raw componentsSeparatedByString:@","]) {
                    NSString *trimmed = [item stringByTrimmingCharactersInSet:
                        [NSCharacterSet whitespaceCharacterSet]];
                    if (trimmed.length) [items addObject:trimmed];
                }
                return items;
            }

            static void TwinSpacePinOAuthSchemesForURL(NSURL *url) {
                NSArray<NSString *> *schemes = TwinSpaceEnvList(@"TWINSPACE_OAUTH_SCHEMES");
                if (!schemes.count) return;
                NSArray<NSString *> *markers = TwinSpaceEnvList(@"TWINSPACE_OAUTH_URL_MARKERS");
                if (markers.count) {
                    NSString *absolute = (url.absoluteString ?: @"").lowercaseString;
                    BOOL matched = NO;
                    for (NSString *marker in markers) {
                        if ([absolute containsString:marker.lowercaseString]) {
                            matched = YES;
                            break;
                        }
                    }
                    if (!matched) return;
                }
                NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
                if (!bundleID.length) return;
                setenv("TWINSPACE_SCHEME_PIN_ACTIVE", "1", 1);
                for (NSString *scheme in schemes) {
                    OSStatus status = LSSetDefaultHandlerForURLScheme(
                        (__bridge CFStringRef)scheme, (__bridge CFStringRef)bundleID);
                    TwinSpaceLog(@"pin oauth scheme %@ -> %@ status=%d", scheme, bundleID, (int)status);
                }
                unsetenv("TWINSPACE_SCHEME_PIN_ACTIVE");
            }

            static OSStatus TwinSpaceLSSetDefaultHandlerForURLScheme(CFStringRef scheme, CFStringRef bundleID) {
                NSString *schemeString = (__bridge NSString *)scheme;
                NSArray<NSString *> *allowed = TwinSpaceEnvList(@"TWINSPACE_SCHEME_ALLOW_REGISTRATION");
                if ([allowed containsObject:schemeString]) {
                    return LSSetDefaultHandlerForURLScheme(scheme, bundleID);
                }
                const char *active = getenv("TWINSPACE_SCHEME_PIN_ACTIVE");
                if (!active || strcmp(active, "1") != 0) {
                    TwinSpaceLog(@"blocked scheme registration %@", schemeString);
                    return noErr;
                }
                return LSSetDefaultHandlerForURLScheme(scheme, bundleID);
            }

            TWINSPACE_DYLD_INTERPOSE(TwinSpaceLSSetDefaultHandlerForURLScheme, LSSetDefaultHandlerForURLScheme)

            static NSString *TwinSpaceBrowserExecutable(NSString *appPath) {
                if (!appPath.length) return nil;
                BOOL isDirectory = NO;
                if (![[NSFileManager defaultManager] fileExistsAtPath:appPath isDirectory:&isDirectory]) {
                    return nil;
                }
                if (isDirectory) {
                    NSBundle *bundle = [NSBundle bundleWithPath:appPath];
                    NSString *executable = [bundle executablePath];
                    if (executable.length) return executable;
                    return [appPath stringByAppendingPathComponent:@"Contents/MacOS/Google Chrome"];
                }
                return appPath;
            }

            static BOOL TwinSpaceOpenInBrowser(NSURL *url) {
                if (!url) return NO;
                NSString *scheme = url.scheme.lowercaseString;
                if (![scheme isEqualToString:@"http"] && ![scheme isEqualToString:@"https"]) return NO;
                NSString *appPath = TwinSpaceEnv(@"TWINSPACE_BROWSER_APP_PATH");
                NSString *dataDir = TwinSpaceEnv(@"TWINSPACE_BROWSER_DATA_DIR");
                if (!dataDir.length) return NO;
                NSString *fallbackPath = TwinSpaceEnv(@"TWINSPACE_BROWSER_FALLBACK_APP_PATH");
                if (!fallbackPath.length) fallbackPath = @"/Applications/Google Chrome.app";
                TwinSpacePinOAuthSchemesForURL(url);
                NSString *executable = TwinSpaceBrowserExecutable(appPath);
                if (!executable.length ||
                    ![[NSFileManager defaultManager] isExecutableFileAtPath:executable]) {
                    TwinSpaceLog(@"browser executable unavailable: %@; falling back to %@",
                           appPath, fallbackPath);
                    executable = TwinSpaceBrowserExecutable(fallbackPath);
                }
                if (!executable.length ||
                    ![[NSFileManager defaultManager] isExecutableFileAtPath:executable]) {
                    return NO;
                }
                NSMutableArray<NSString *> *arguments = [NSMutableArray array];
                [arguments addObject:[@"--user-data-dir=" stringByAppendingString:dataDir]];
                NSString *extra = TwinSpaceEnv(@"TWINSPACE_BROWSER_EXTRA_ARGS");
                if (extra.length) {
                    for (NSString *part in [extra componentsSeparatedByCharactersInSet:
                            [NSCharacterSet whitespaceCharacterSet]]) {
                        if (part.length) [arguments addObject:part];
                    }
                }
                [arguments addObject:url.absoluteString];
                NSTask *task = [[NSTask alloc] init];
                task.executableURL = [NSURL fileURLWithPath:executable];
                task.arguments = arguments;
                NSMutableDictionary *environment =
                    [[[NSProcessInfo processInfo] environment] mutableCopy];
                [environment removeObjectForKey:@"DYLD_INSERT_LIBRARIES"];
                [environment removeObjectForKey:@"DYLD_LIBRARY_PATH"];
                [environment removeObjectForKey:@"DYLD_FRAMEWORK_PATH"];
                NSString *realHome = TwinSpaceEnv(@"REAL_USER_HOME");
                if (realHome.length) environment[@"HOME"] = realHome;
                task.environment = environment;
                task.standardOutput = [NSFileHandle fileHandleWithNullDevice];
                task.standardError = [NSFileHandle fileHandleWithNullDevice];
                NSError *error = nil;
                BOOL launched = [task launchAndReturnError:&error];
                NSString *safeURL = [NSString stringWithFormat:@"%@://%@%@",
                    url.scheme ?: @"", url.host ?: @"", url.path ?: @""];
                TwinSpaceLog(@"browser launch %@ -> %@ dataDir=%@ error=%@",
                       safeURL, executable, dataDir, error);
                return launched;
            }

            static BOOL (*TwinSpaceOrigOpenURL)(id, SEL, NSURL *);
            static BOOL (*TwinSpaceOrigOpenURLOptions)(id, SEL, NSURL *, NSWorkspaceLaunchOptions,
                                                 NSDictionary *, NSError **);
            static void (*TwinSpaceOrigOpenURLConfig)(id, SEL, NSURL *, id,
                                                void (^)(NSRunningApplication *, NSError *));
            static void (*TwinSpaceOrigOpenURLsWithApp)(id, SEL, NSArray<NSURL *> *, NSURL *, id,
                                                  void (^)(NSArray<NSRunningApplication *> *, NSError *));

            static BOOL TwinSpaceOpenURL(id self, SEL _cmd, NSURL *url) {
                if (TwinSpaceOpenInBrowser(url)) return YES;
                return TwinSpaceOrigOpenURL ? TwinSpaceOrigOpenURL(self, _cmd, url) : NO;
            }

            static BOOL TwinSpaceOpenURLOptions(id self, SEL _cmd, NSURL *url,
                                          NSWorkspaceLaunchOptions options,
                                          NSDictionary *configuration, NSError **error) {
                if (TwinSpaceOpenInBrowser(url)) return YES;
                return TwinSpaceOrigOpenURLOptions
                    ? TwinSpaceOrigOpenURLOptions(self, _cmd, url, options, configuration, error)
                    : NO;
            }

            static void TwinSpaceOpenURLConfig(id self, SEL _cmd, NSURL *url, id configuration,
                                         void (^completion)(NSRunningApplication *, NSError *)) {
                if (TwinSpaceOpenInBrowser(url)) {
                    if (completion) completion(nil, nil);
                    return;
                }
                if (TwinSpaceOrigOpenURLConfig) {
                    TwinSpaceOrigOpenURLConfig(self, _cmd, url, configuration, completion);
                } else if (completion) {
                    completion(nil, [NSError errorWithDomain:@"TwinSpaceIsolation" code:1 userInfo:nil]);
                }
            }

            static void TwinSpaceOpenURLsWithApp(id self, SEL _cmd, NSArray<NSURL *> *urls,
                                           NSURL *applicationURL, id configuration,
                                           void (^completion)(NSArray<NSRunningApplication *> *, NSError *)) {
                if (urls.count == 1 && TwinSpaceOpenInBrowser(urls.firstObject)) {
                    if (completion) completion(@[], nil);
                    return;
                }
                if (TwinSpaceOrigOpenURLsWithApp) {
                    TwinSpaceOrigOpenURLsWithApp(self, _cmd, urls, applicationURL, configuration, completion);
                } else if (completion) {
                    completion(@[], [NSError errorWithDomain:@"TwinSpaceIsolation" code:2 userInfo:nil]);
                }
            }

            __attribute__((constructor)) static void TwinSpaceInstallWorkspaceHooks(void) {
                Class workspace = [NSWorkspace class];
                Method method = class_getInstanceMethod(workspace, @selector(openURL:));
                if (method) {
                    TwinSpaceOrigOpenURL = (BOOL (*)(id, SEL, NSURL *))
                        method_setImplementation(method, (IMP)TwinSpaceOpenURL);
                }
                method = class_getInstanceMethod(workspace,
                    NSSelectorFromString(@"openURL:options:configuration:error:"));
                if (method) {
                    TwinSpaceOrigOpenURLOptions = (BOOL (*)(id, SEL, NSURL *, NSWorkspaceLaunchOptions,
                                                      NSDictionary *, NSError **))
                        method_setImplementation(method, (IMP)TwinSpaceOpenURLOptions);
                }
                method = class_getInstanceMethod(workspace,
                    NSSelectorFromString(@"openURL:configuration:completionHandler:"));
                if (method) {
                    TwinSpaceOrigOpenURLConfig = (void (*)(id, SEL, NSURL *, id,
                                                     void (^)(NSRunningApplication *, NSError *)))
                        method_setImplementation(method, (IMP)TwinSpaceOpenURLConfig);
                }
                method = class_getInstanceMethod(workspace,
                    NSSelectorFromString(@"openURLs:withApplicationAtURL:configuration:completionHandler:"));
                if (method) {
                    TwinSpaceOrigOpenURLsWithApp = (void (*)(id, SEL, NSArray<NSURL *> *, NSURL *, id,
                                                       void (^)(NSArray<NSRunningApplication *> *, NSError *)))
                        method_setImplementation(method, (IMP)TwinSpaceOpenURLsWithApp);
                }
                TwinSpaceLog(@"isolation hooks installed");
            }
        ''').strip()

        clang_cmd = cls._resolve_clang_command()
        return (
            f"mkdir -p {dst_frameworks}\n"
            f"{clang_cmd} -dynamiclib -fobjc-arc -O2 -arch arm64 -arch x86_64 "
            f"-framework Foundation -framework AppKit -framework Security -framework CoreServices "
            f"-framework IOKit -framework DiskArbitration "
            f"-install_name @executable_path/../Frameworks/libtwinspace_isolation.dylib "
            f"-o {dst_frameworks}/libtwinspace_isolation.dylib -x objective-c - << 'TWINSPACE_ISOLATION_EOF'\n"
            + source
            + "\nTWINSPACE_ISOLATION_EOF\n"
            f"chmod +x {dst_frameworks}/libtwinspace_isolation.dylib\n"
        )

    @classmethod
    def _check_macho_injection_headroom(
        cls,
        macho_path: Path,
        dylib_path: str = "@executable_path/../Frameworks/libtwinspace_env.dylib",
    ) -> tuple[bool, str]:
        """Verify that a Mach-O binary has enough free padding in its header to safely inject LC_LOAD_DYLIB.

        Returns:
            (is_safe, reason): True if safe to inject; False with reason if insufficient or unsupported.
        """
        if not macho_path.exists() or not macho_path.is_file():
            return False, f"File does not exist: {macho_path}"

        try:
            with open(macho_path, "rb") as fp:
                data = fp.read()
        except OSError as e:
            return False, f"Failed to read binary: {e}"

        if len(data) < 32:
            return False, "File too small to be Mach-O"

        magic = struct.unpack("<I", data[:4])[0]
        archs: list[tuple[int, int]] = []
        if magic in (0xCAFEBABE, 0xBEBAFECA):
            nfat = struct.unpack(">I", data[4:8])[0]
            for i in range(nfat):
                cputype, cpusubtype, offset, size, align = struct.unpack(
                    ">IIIII", data[8 + i * 20 : 28 + i * 20]
                )
                archs.append((offset, size))
        elif magic in (0xFEEDFACF, 0xCFFAEDFE):
            archs.append((0, len(data)))
        else:
            return False, f"Unsupported binary format (magic: {hex(magic)})"

        cmdsize = 24 + len(dylib_path.encode("utf-8") + b"\x00")
        if cmdsize % 8 != 0:
            cmdsize += 8 - (cmdsize % 8)

        for offset, size in archs:
            if offset + 32 > len(data):
                return False, "Malformed Mach-O slice"
            m_magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack(
                "<IIIIIIII", data[offset : offset + 32]
            )
            if filetype != 2:  # MH_EXECUTE
                return False, f"Mach-O filetype {filetype} is not MH_EXECUTE"

            cmd_ptr = offset + 32
            first_section_offset = size
            for _ in range(ncmds):
                if cmd_ptr + 8 > len(data):
                    return False, "Malformed load commands"
                cmd, csize = struct.unpack("<II", data[cmd_ptr : cmd_ptr + 8])
                if cmd == 0x19:  # LC_SEGMENT_64
                    if cmd_ptr + 68 <= len(data):
                        nsects = struct.unpack("<I", data[cmd_ptr + 64 : cmd_ptr + 68])[0]
                        sect_ptr = cmd_ptr + 72
                        for _ in range(nsects):
                            if sect_ptr + 52 <= len(data):
                                s_size = struct.unpack("<Q", data[sect_ptr + 40 : sect_ptr + 48])[0]
                                s_offset = struct.unpack("<I", data[sect_ptr + 48 : sect_ptr + 52])[0]
                                if s_size > 0 and s_offset > 0:
                                    if s_offset < first_section_offset:
                                        first_section_offset = s_offset
                            sect_ptr += 80
                cmd_ptr += csize

            end_of_cmds = 32 + sizeofcmds
            padding = first_section_offset - end_of_cmds
            if padding < cmdsize:
                return False, f"Insufficient header padding ({padding} bytes available, {cmdsize} required)"

        return True, "OK"




class SoftCloneEngine(CloneEngine):
    """Creates a lightweight wrapper app that launches the original binary with custom args and environment."""

    @classmethod
    def execute(cls, task: CloneTask, needs_admin: bool = False) -> None:
        """Execute soft clone script.

        Args:
            task: The clone task parameters.
            needs_admin: Whether administrator elevation is required.
        """
        if getattr(task.source, "is_ios_app", False):
            from twinspace.core.i18n import t
            raise CloneError(t("clone_err_ios_wrapper_unsupported"))

        effective_env = cls._resolve_env(task)
        if cls._needs_isolation_hook(effective_env):
            raise CloneError(
                "This recipe requires a hard clone for keychain/browser/OAuth isolation; "
                "re-run without --strategy soft_clone."
            )

        task.actual_injection_strategy = "launcher"

        src_plist = shlex.quote(str(task.source.path / "Contents" / "Info.plist"))
        dst_app = shlex.quote(str(task.dest_path))
        dst_mac = shlex.quote(str(task.dest_path / "Contents" / "MacOS"))
        dst_plist = shlex.quote(str(task.dest_path / "Contents" / "Info.plist"))

        bin_name = (
            task.source.executable.name
            if task.source.executable and task.source.executable.name
            else task.source.app_name
        )
        wrapper = shlex.quote(str(task.dest_path / "Contents" / "MacOS" / bin_name))

        lang_env, lang_args = cls._build_language_env_and_args(task)
        valid_launch_args = cls._get_validated_launch_args(task)

        codex_init_cmd = cls._build_codex_init_cmd(task)
        gemini_init_cmd = cls._build_gemini_init_cmd(task)
        claude_init_cmd = cls._build_claude_init_cmd(task)

        args_list = cls._combine_launch_args(valid_launch_args, lang_args, task)


        symlink_snippet = cls._build_symlink_whitelist_snippet(task)
        pref_seeding = cls._build_preference_seeding_snippet(task)
        proxy_env = cls._build_proxy_env(task)

        target_bin_statement = f'    char *real_bin = "{_escape_c_string(str(task.source.executable))}";'
        c_launcher_cmd = cls._build_c_launcher_compile_cmd(
            dst_wrapper=wrapper,
            target_bin_statement=target_bin_statement,
            effective_env=effective_env,
            proxy_env=proxy_env,
            lang_env=lang_env,
            args_list=args_list,
            data_dir=task.data_dir,
        )

        src_resources = shlex.quote(str(task.source.path / "Contents" / "Resources"))
        dst_resources = shlex.quote(str(task.dest_path / "Contents" / "Resources"))
        dst_parent = shlex.quote(str(task.dest_path.parent))
        data_dirs_cmd = cls._build_data_dirs_cmd(task, effective_env)

        # Effective display name: explicit override > clone_name
        effective_display_name = task.display_name if task.display_name else task.clone_name
        display_name_cmd = cls._build_display_name_cmd(effective_display_name, dst_plist, dst_resources)
        icon_cmd = cls._build_icon_cmd(task, dst_resources, dst_plist)
        lsregister_cmd = cls._build_lsregister_cmd(dst_app)

        script = f"""set -e
mkdir -p {dst_parent}
{data_dirs_cmd}
rm -rf {dst_app}
mkdir -p {dst_mac}
{codex_init_cmd}{gemini_init_cmd}{claude_init_cmd}# Copy Resources dir so the app icon (.icns) and other assets are available

if [ -d {src_resources} ]; then
    cp -Rc {src_resources} {dst_resources} 2>/dev/null || (rm -rf {dst_resources} 2>/dev/null; cp -R {src_resources} {dst_resources})
fi
cp {src_plist} {dst_plist}
chmod -R u+w {dst_app} 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier {task.new_bundle_id}" {dst_plist}
/usr/libexec/PlistBuddy -c "Delete :TeamIdentifier" {dst_plist} 2>/dev/null || true
{display_name_cmd}
{icon_cmd}{c_launcher_cmd}
{pref_seeding}
{symlink_snippet}
codesign --force --deep --sign - {dst_app} 2>/dev/null || true
{lsregister_cmd}
"""
        try:
            Runner.run(script, needs_admin)
        except Exception:
            try:
                Runner.run(f"rm -rf {dst_app}", needs_admin)
            except (CloneError, OSError):
                pass
            raise


class HardCloneEngine(CloneEngine):
    """Creates a full physical clone of the app bundle with binary renaming, wrapper, and re-signing."""


    @classmethod
    def _build_singleton_patch_cmd(cls, dest_path: Path) -> str:
        """Return a shell snippet that patches ProcessSingleton in embedded frameworks if present.

        Some Electron/Chromium apps (e.g. Feishu/Lark) contain custom ProcessSingleton logic
        in embedded framework binaries (like Lark Framework.framework). When launched as a second
        instance, they call ProcessSingleton::NotifyOtherProcessOrCreate() which immediately signals
        the first instance and exits (exit code 34). This command scans embedded Mach-O binaries in
        Contents/Frameworks/ and patches the bl NotifyOtherProcessOrCreate call with `mov w0, #0; nop`
        so every clone runs concurrently as an independent primary instance.
        """
        dest_quoted = shlex.quote(str(dest_path))
        return textwrap.dedent(f"""\
            # Patch ProcessSingleton in embedded frameworks if present (e.g. Feishu/Lark, ChatGPT)
            # dest_path travels via an env var so its quoting never collides with the nested python -c.
            TWINSPACE_PATCH_TARGET={dest_quoted} python3 -c '
import os, glob, struct
frameworks_dir = os.path.join(os.environ["TWINSPACE_PATCH_TARGET"], "Contents", "Frameworks")
target_str = b"Failed to create a ProcessSingleton for your profile directory."
if os.path.isdir(frameworks_dir):
    for root, _, files in os.walk(frameworks_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            if os.path.islink(fpath) or not os.path.isfile(fpath):
                continue
            try:
                if os.path.getsize(fpath) < 1000000:
                    continue
                with open(fpath, "rb") as f:
                    header = f.read(4)
                    if header not in (b"\\xcf\\xfa\\xed\\xfe", b"\\xfe\\xed\\xfa\\xcf"):
                        continue
                    f.seek(0)
                    data = bytearray(f.read())
                str_idx = data.find(target_str)
                if str_idx == -1:
                    continue
                page = str_idx & ~0xFFF
                page_offset = str_idx & 0xFFF
                found_pc = None
                for i in range(0, len(data) - 8, 4):
                    w1, w2 = struct.unpack_from("<II", data, i)
                    if (w1 & 0x9F000000) == 0x90000000:
                        immlo = (w1 >> 29) & 3
                        immhi = (w1 >> 5) & 0x7FFFF
                        imm = (immhi << 2) | immlo
                        if imm & (1 << 20): imm -= (1 << 21)
                        if (i & ~0xFFF) + (imm << 12) == page:
                            if (w2 & 0xFFC00000) == 0x91000000 and ((w2 >> 10) & 0xFFF) == page_offset:
                                found_pc = i
                                break
                if found_pc is None:
                    continue
                cmp_pos = None
                for pos in range(found_pc - 4, max(0, found_pc - 300), -4):
                    w, = struct.unpack_from("<I", data, pos)
                    if (w & 0xFFE0001F) == 0x7100001F:
                        cmp_pos = pos
                        break
                if cmp_pos is None:
                    continue
                for pos in range(cmp_pos - 4, max(0, cmp_pos - 40), -4):
                    w_bl, = struct.unpack_from("<I", data, pos)
                    if (w_bl & 0xFC000000) == 0x94000000:
                        imm26 = w_bl & 0x03FFFFFF
                        if imm26 & (1 << 25): imm26 -= (1 << 26)
                        bl_target = pos + (imm26 << 2)
                        if 0 <= bl_target < len(data) - 8:
                            struct.pack_into("<II", data, bl_target, 0x52800000, 0xD65F03C0)
                        struct.pack_into("<II", data, pos, 0x52800000, 0xD503201F)
                        with open(fpath, "wb") as f:
                            f.write(data)
                        break
            except Exception:
                pass
' 2>/dev/null || true
        """)

    @classmethod
    def _build_cef_patch_cmd(cls, dest_path: Path) -> str:
        """Patch Chromium Embedded Framework to disable Seatbelt sandbox and set no_sandbox=1."""
        dest_quoted = shlex.quote(str(dest_path))
        return textwrap.dedent(f"""\
            # Patch CEF framework no_sandbox and bypass child process Seatbelt sandbox if present
            TWINSPACE_PATCH_TARGET={dest_quoted} python3 -c '
import os
dst = os.environ["TWINSPACE_PATCH_TARGET"]
cef_path = os.path.join(dst, "Contents", "Frameworks", "Chromium Embedded Framework.framework", "Versions", "A", "Chromium Embedded Framework")
if not os.path.exists(cef_path):
    cef_path = os.path.join(dst, "Contents", "Frameworks", "Chromium Embedded Framework.framework", "Chromium Embedded Framework")
if os.path.exists(cef_path) and not os.path.islink(cef_path):
    try:
        with open(cef_path, "rb") as f:
            data = bytearray(f.read())
        # 1. Patch cef_initialize settings copy to force no_sandbox = 1
        needle1 = bytes.fromhex("f50302aaf30301aaf40300aa080840b9280800b9")
        pos1 = data.find(needle1)
        if pos1 != -1:
            patch_off1 = pos1 + 12
            if data[patch_off1:patch_off1+4] == bytes.fromhex("080840b9"):
                data[patch_off1:patch_off1+4] = bytes.fromhex("28008052")
        # 2. Patch ChildProcessLauncherHelper to bypass Seatbelt sandbox branches
        needle2 = bytes.fromhex("010a005448260035e8c343391f05007180250054")
        pos2 = data.find(needle2)
        if pos2 != -1:
            data[pos2+4:pos2+8] = bytes.fromhex("1f2003d5")
            data[pos2+16:pos2+20] = bytes.fromhex("1f2003d5")
        # 3. Patch ChildProcessLauncherHelper Seatbelt compile entry to directly branch to launch
        needle3 = bytes.fromhex("e00315aae4010094f80300aa40e5054f")
        pos3 = data.find(needle3)
        if pos3 != -1:
            data[pos3:pos3+4] = bytes.fromhex("34000014")
        # 4. Patch FallBackToNextGpuMode FATAL abort ("GPU process isn'\''t usable. Goodbye.") to safe return
        needle4 = bytes.fromhex("ff4305d1f44f13a9fd7b14a9fd030591")
        pos4 = data.find(needle4)
        if pos4 != -1:
            data[pos4:pos4+4] = bytes.fromhex("d0ffff17")
        with open(cef_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
' 2>/dev/null || true
        """)

    @classmethod
    def _cocoa_hook_source(cls) -> str:
        """Return the Objective-C source code for Cocoa/POSIX home directory interpose hook."""
        return textwrap.dedent("""\
            #import <Foundation/Foundation.h>
            #include <pwd.h>
            #include <unistd.h>
            #include <stdlib.h>
            #include <string.h>

            static NSString *my_NSHomeDirectory(void) {
                const char *custom = getenv("HOME");
                if (custom && custom[0]) {
                    return [NSString stringWithUTF8String:custom];
                }
                return NSHomeDirectory();
            }

            static NSString *my_NSHomeDirectoryForUser(NSString *userName) {
                const char *custom = getenv("HOME");
                if (custom && custom[0]) {
                    return [NSString stringWithUTF8String:custom];
                }
                return NSHomeDirectoryForUser(userName);
            }

            static NSString *my_NSTemporaryDirectory(void) {
                const char *custom = getenv("TMPDIR");
                if (custom && custom[0]) {
                    NSString *t = [NSString stringWithUTF8String:custom];
                    if (![t hasSuffix:@"/"]) {
                        t = [t stringByAppendingString:@"/"];
                    }
                    [[NSFileManager defaultManager] createDirectoryAtPath:t withIntermediateDirectories:YES attributes:nil error:nil];
                    return t;
                }
                return NSTemporaryDirectory();
            }

            static NSArray<NSString *> *my_NSSearchPathForDirectoriesInDomains(
                NSSearchPathDirectory directory,
                NSSearchPathDomainMask domainMask,
                BOOL expandTilde) {
                const char *custom_home = getenv("HOME");
                if (custom_home && custom_home[0] && (domainMask & NSUserDomainMask)) {
                    NSString *homeStr = [NSString stringWithUTF8String:custom_home];
                    NSString *sub = nil;
                    switch (directory) {
                        case NSApplicationSupportDirectory:
                            sub = @"Library/Application Support";
                            break;
                        case NSCachesDirectory:
                            sub = @"Library/Caches";
                            break;
                        case NSLibraryDirectory:
                            sub = @"Library";
                            break;
                        case NSDocumentDirectory:
                            sub = @"Documents";
                            break;
                        default:
                            break;
                    }
                    if (sub) {
                        NSString *full = [homeStr stringByAppendingPathComponent:sub];
                        [[NSFileManager defaultManager] createDirectoryAtPath:full withIntermediateDirectories:YES attributes:nil error:nil];
                        return @[full];
                    }
                }
                return NSSearchPathForDirectoriesInDomains(directory, domainMask, expandTilde);
            }

            static struct passwd *my_getpwuid(uid_t uid) {
                struct passwd *pw = getpwuid(uid);
                if (pw) {
                    const char *custom_home = getenv("HOME");
                    if (custom_home && custom_home[0]) {
                        __thread static struct passwd fake_pw;
                        fake_pw = *pw;
                        fake_pw.pw_dir = (char *)custom_home;
                        return &fake_pw;
                    }
                }
                return pw;
            }

            static int my_getpwuid_r(uid_t uid, struct passwd *pwd, char *buffer, size_t bufsize, struct passwd **result) {
                int ret = getpwuid_r(uid, pwd, buffer, bufsize, result);
                if (ret == 0 && result && *result) {
                    const char *custom_home = getenv("HOME");
                    if (custom_home && custom_home[0]) {
                        pwd->pw_dir = (char *)custom_home;
                    }
                }
                return ret;
            }

            static size_t my_confstr(int name, char *buf, size_t len) {
                if (name == _CS_DARWIN_USER_TEMP_DIR || name == _CS_DARWIN_USER_CACHE_DIR) {
                    const char *custom_tmp = getenv("TMPDIR");
                    if (custom_tmp && custom_tmp[0]) {
                        size_t n = strlen(custom_tmp) + 1;
                        if (buf && len > 0) {
                            strncpy(buf, custom_tmp, len);
                            buf[len - 1] = 0;
                        }
                        return n;
                    }
                }
                return confstr(name, buf, len);
            }

            #define DYLD_INTERPOSE(_replacement,_replacee) \\
               __attribute__((used)) static struct{ const void* replacement; const void* replacee; } _interpose_##_replacee \\
                        __attribute__ ((section ("__DATA,__interpose"))) = { (const void*)(unsigned long)&_replacement, (const void*)(unsigned long)&_replacee };

            DYLD_INTERPOSE(my_NSHomeDirectory, NSHomeDirectory)
            DYLD_INTERPOSE(my_NSHomeDirectoryForUser, NSHomeDirectoryForUser)
            DYLD_INTERPOSE(my_NSTemporaryDirectory, NSTemporaryDirectory)
            DYLD_INTERPOSE(my_NSSearchPathForDirectoriesInDomains, NSSearchPathForDirectoriesInDomains)
            DYLD_INTERPOSE(my_getpwuid, getpwuid)
            DYLD_INTERPOSE(my_getpwuid_r, getpwuid_r)
            DYLD_INTERPOSE(my_confstr, confstr)
        """).strip()

    @classmethod
    def _build_lark_isolation_cmd(cls, task: CloneTask) -> str:
        """Return a shell snippet to compile libtwinspace_lark_hook.dylib and strip URL schemes for Feishu/Lark."""
        is_lark = (
            getattr(task.recipe, "patch_lark_isolation", False)
            or getattr(task.source, "bundle_id", "") == "com.electron.lark"
            or getattr(task, "new_bundle_id", "").startswith("com.electron.lark")
        )
        if not is_lark:
            return ""

        dst_frameworks = shlex.quote(str(task.dest_path / "Contents" / "Frameworks"))
        rel_plist = getattr(task.source, "relative_plist_path", Path("Contents/Info.plist"))
        dst_plist = shlex.quote(str(task.dest_path / rel_plist))

        strip_schemes_cmd = ""
        if getattr(task.recipe, "strip_url_schemes", False) or is_lark:
            strip_schemes_cmd = f'/usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" {dst_plist} 2>/dev/null || true\n'

        hook_m = cls._cocoa_hook_source()
        clang_cmd = cls._resolve_clang_command()

        return textwrap.dedent(f"""\
            # Lark/Feishu isolation: compile Cocoa/POSIX hook dylib and strip URL schemes
            {strip_schemes_cmd}mkdir -p {dst_frameworks}
            {clang_cmd} -dynamiclib -O2 -arch arm64 -arch x86_64 -framework Foundation -install_name @executable_path/../Frameworks/libtwinspace_lark_hook.dylib -o {dst_frameworks}/libtwinspace_lark_hook.dylib -x objective-c - << 'LARK_HOOK_EOF'
{hook_m}
LARK_HOOK_EOF
            chmod +x {dst_frameworks}/libtwinspace_lark_hook.dylib
        """).strip() + "\n"

    @classmethod
    def _build_chatgpt_isolation_cmd(cls, task: CloneTask) -> str:
        """Return a shell snippet to compile libtwinspace_chatgpt_hook.dylib and strip URL schemes for ChatGPT."""
        is_chatgpt = (
            getattr(task.recipe, "patch_chatgpt_isolation", False)
            or getattr(task.source, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
            or getattr(task.recipe, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
            or getattr(task, "new_bundle_id", "").startswith("com.openai.codex")
            or getattr(task, "new_bundle_id", "").startswith("com.openai.chat")
        )
        if not is_chatgpt:
            return ""

        dst_frameworks = shlex.quote(str(task.dest_path / "Contents" / "Frameworks"))
        rel_plist = getattr(task.source, "relative_plist_path", Path("Contents/Info.plist"))
        dst_plist = shlex.quote(str(task.dest_path / rel_plist))

        strip_schemes_cmd = ""
        if getattr(task.recipe, "strip_url_schemes", False) or is_chatgpt:
            strip_schemes_cmd = f'/usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" {dst_plist} 2>/dev/null || true\n'

        hook_m = cls._cocoa_hook_source()
        clang_cmd = cls._resolve_clang_command()

        return textwrap.dedent(f"""\
            # ChatGPT isolation: compile Cocoa/POSIX hook dylib and strip URL schemes
            {strip_schemes_cmd}mkdir -p {dst_frameworks}
            {clang_cmd} -dynamiclib -O2 -arch arm64 -arch x86_64 -framework Foundation -install_name @executable_path/../Frameworks/libtwinspace_chatgpt_hook.dylib -o {dst_frameworks}/libtwinspace_chatgpt_hook.dylib -x objective-c - << 'CHATGPT_HOOK_EOF'
{hook_m}
CHATGPT_HOOK_EOF
            chmod +x {dst_frameworks}/libtwinspace_chatgpt_hook.dylib
        """).strip() + "\n"

    @staticmethod
    def patch_framework_singletons(dest_path: Path) -> bool:
        """Python helper to patch ProcessSingleton in embedded frameworks for testing and tools."""
        import struct
        patched_any = False
        target_str = b"Failed to create a ProcessSingleton for your profile directory."

        frameworks_dir = dest_path / "Contents" / "Frameworks"
        if not frameworks_dir.is_dir():
            return False

        for root, _, files in os.walk(frameworks_dir):
            for fname in files:
                fpath = Path(root) / fname
                if fpath.is_symlink() or not fpath.is_file():
                    continue
                try:
                    if fpath.stat().st_size < 1_000_000:
                        continue
                    with open(fpath, "rb") as f:
                        header = f.read(4)
                        if header not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
                            continue
                        f.seek(0)
                        data = bytearray(f.read())

                    if len(data) >= 8:
                        cputype = struct.unpack_from("<I", data, 4)[0]
                        if cputype == 0x01000007:  # CPU_TYPE_X86_64: skip Intel binaries
                            continue

                    str_idx = data.find(target_str)
                    if str_idx == -1:
                        continue

                    page = str_idx & ~0xFFF
                    page_offset = str_idx & 0xFFF

                    found_pc = None
                    for i in range(0, len(data) - 8, 4):
                        w1, w2 = struct.unpack_from("<II", data, i)
                        if (w1 & 0x9F000000) == 0x90000000:
                            immlo = (w1 >> 29) & 3
                            immhi = (w1 >> 5) & 0x7FFFF
                            imm = (immhi << 2) | immlo
                            if imm & (1 << 20):
                                imm -= 1 << 21
                            if (i & ~0xFFF) + (imm << 12) == page:
                                if (w2 & 0xFFC00000) == 0x91000000 and ((w2 >> 10) & 0xFFF) == page_offset:
                                    found_pc = i
                                    break

                    if found_pc is None:
                        continue

                    cmp_pos = None
                    for pos in range(found_pc - 4, max(0, found_pc - 300), -4):
                        (w,) = struct.unpack_from("<I", data, pos)
                        if (w & 0xFFE0001F) == 0x7100001F:
                            cmp_pos = pos
                            break

                    if cmp_pos is None:
                        continue

                    for pos in range(cmp_pos - 4, max(0, cmp_pos - 40), -4):
                        (w_bl,) = struct.unpack_from("<I", data, pos)
                        if (w_bl & 0xFC000000) == 0x94000000:
                            imm26 = w_bl & 0x03FFFFFF
                            if imm26 & (1 << 25):
                                imm26 -= 1 << 26
                            bl_target = pos + (imm26 << 2)
                            if 0 <= bl_target < len(data) - 8:
                                struct.pack_into("<II", data, bl_target, 0x52800000, 0xD65F03C0)
                            struct.pack_into("<II", data, pos, 0x52800000, 0xD503201F)
                            with open(fpath, "wb") as f:
                                f.write(data)
                            patched_any = True
                            break
                except Exception:
                    continue

        return patched_any

    @classmethod
    def _build_framework_prune_cmd(cls, dest_path: Path) -> str:
        """Return a shell snippet that prunes stale/orphaned framework versions in Contents/Frameworks.

        When apps like Google Chrome update in-place, previous versions remain inside
        Contents/Frameworks/*.framework/Versions/ alongside the active version pointed to by Current.
        Leaving stale versions causes 'embedded framework contains modified or invalid version'
        errors during codesign verification, and wastes hundreds of megabytes of disk space.
        """
        dst = shlex.quote(str(dest_path))
        return textwrap.dedent(f"""\
            # Prune stale/inactive framework versions to ensure clean codesigning and save disk space
            if [ -d {dst}/Contents/Frameworks ]; then
                find {dst}/Contents/Frameworks -name "*.framework" -type d 2>/dev/null | while read -r fw; do
                    if [ -d "$fw/Versions" ] && [ -L "$fw/Versions/Current" ]; then
                        curr_target=$(readlink "$fw/Versions/Current")
                        curr_target_base=$(basename "$curr_target")
                        for ver_path in "$fw/Versions"/*; do
                            if [ -d "$ver_path" ] && [ ! -L "$ver_path" ]; then
                                ver_name=$(basename "$ver_path")
                                if [ "$ver_name" != "$curr_target_base" ]; then
                                    rm -rf "$ver_path" 2>/dev/null || true
                                fi
                            fi
                        done
                    fi
                done
            fi
        """).strip() + "\n"

    @staticmethod
    def _build_process_name_cmd(task: CloneTask, main_binary: Path) -> str:
        """Rename real Mach-O processes, retaining aliases for hardcoded helper paths."""
        rel_plist = getattr(task.source, "relative_plist_path", Path("Contents/Info.plist"))
        is_chromium = (
            (getattr(task.recipe, "app_type", "") or "").lower() in ("chromium", "electron")
            or (task.dest_path / "Contents/Frameworks/Electron Framework.framework").exists()
            or (task.dest_path / "Contents/Frameworks/QQNT.framework").exists()
            or (task.dest_path / "Contents/Frameworks/Chromium Embedded Framework.framework").exists()
            or (task.dest_path / "Contents/Resources/app.asar").exists()
            or (task.dest_path / "Contents/Resources/electron.asar").exists()
            or (task.dest_path / "Contents/Resources/app/application.asar").exists()
            or bool(list(task.dest_path.glob("Contents/Frameworks/*Helper*.app")))
        )
        args = shlex.join([
            str(task.dest_path),
            task.clone_name,
            str(main_binary),
            str(rel_plist),
            "1" if is_chromium else "0",
        ])
        return f"python3 - {args} << 'PROCESS_NAMES_PY'\n" + textwrap.dedent(r'''
            import os
            import plistlib
            import struct
            import sys
            import tempfile
            from pathlib import Path

            app, name, main = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
            rel_plist_str = sys.argv[4] if len(sys.argv) > 4 else "Contents/Info.plist"
            is_chromium = (
                (sys.argv[5] == "1") if len(sys.argv) > 5 else False
            ) or (
                (app / "Contents/Frameworks/Electron Framework.framework").exists()
                or (app / "Contents/Frameworks/QQNT.framework").exists()
                or (app / "Contents/Frameworks/Chromium Embedded Framework.framework").exists()
                or (app / "Contents/Resources/app.asar").exists()
                or (app / "Contents/Resources/electron.asar").exists()
                or (app / "Contents/Resources/app/application.asar").exists()
                or bool(list(app.glob("Contents/Frameworks/*Helper*.app")))
            )
            root_plist = app / rel_plist_str
            if not root_plist.is_file():
                root_plist = app / "Contents/Info.plist"
            if not root_plist.is_file():
                sys.exit(0)

            try:
                root_data = plistlib.loads(root_plist.read_bytes())
            except Exception:
                sys.exit(0)

            root_exe = root_data.get("CFBundleExecutable")
            if not isinstance(root_exe, str) or not root_exe:
                sys.exit(0)

            entry = (root_plist.parent / "MacOS" / root_exe) if (root_plist.parent / "MacOS").is_dir() else (root_plist.parent / root_exe)

            def is_executable(path):
                """Identify thin or universal Mach-O executable files without loading their contents."""
                try:
                    with path.open("rb") as f:
                        magic = f.read(4)
                        if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
                            # Universal binaries: inspect the first architecture's Mach-O header.
                            f.seek(16)
                            wide = magic == b"\xca\xfe\xba\xbf"
                            data = f.read(8 if wide else 4)
                            if len(data) < (8 if wide else 4):
                                return False
                            offset = struct.unpack(">Q" if wide else ">I", data)[0]
                            f.seek(offset)
                            magic = f.read(4)
                        if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
                            endian = "<"
                        elif magic in (b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
                            endian = ">"
                        else:
                            return False
                        header = f.read(12)
                        return len(header) == 12 and struct.unpack(endian + "III", header)[2] == 2  # MH_EXECUTE
                except Exception:
                    return False

            moves, plists = {}, []
            walk_dir = app / "Contents" if (app / "Contents").is_dir() else app
            for directory, _, files in os.walk(walk_dir, followlinks=False):
                dir_path = Path(directory)
                if is_chromium:
                    parts = dir_path.parts
                    if "Frameworks" in parts or "Resources" in parts or "PlugIns" in parts:
                        continue
                    if any("Helper" in part for part in parts):
                        continue
                for filename in files:
                    path = dir_path / filename
                    if path.is_symlink() or not path.is_file():
                        continue
                    if filename == "Info.plist":
                        if not is_chromium or path == root_plist:
                            plists.append(path)
                        continue
                    try:
                        if not os.access(path, os.X_OK) or not is_executable(path):
                            continue
                    except Exception:
                        continue
                    # For Chromium/Electron, ONLY rename root main binary and entry launcher.
                    # All secondary binaries, nested sub-apps, and helpers must remain untampered.
                    if is_chromium and path != main and path != entry:
                        continue
                    new_name = name if path == main else name + ("-Launcher" if path == entry else "-" + filename)
                    target = path.with_name(new_name)
                    if path != target:
                        moves[path] = target

            # Validate all destinations before moving anything; never overwrite resources.
            targets = set(moves.values())
            if len(targets) != len(moves):
                raise ValueError("Duplicate process names in cloned app")
            for old, target in moves.items():
                launcher_handoff = old == main and main != entry and target == entry and entry in moves
                if os.path.lexists(target) and not launcher_handoff:
                    raise FileExistsError(f"Process name conflicts with existing file: {target}")

            updates = []
            for plist in plists:
                try:
                    data = plistlib.loads(plist.read_bytes())
                except Exception:
                    continue
                executable = data.get("CFBundleExecutable")
                if not isinstance(executable, str):
                    continue
                folder = (plist.parent / "MacOS") if (plist.parent / "MacOS").is_dir() else plist.parent
                target = moves.get(folder / executable)
                if target:
                    data["CFBundleExecutable"] = target.name
                    updates.append((plist, data))

            # Stage moves so a clone named like the old launcher can take its filename.
            staged = []
            for old, target in moves.items():
                fd, temporary = tempfile.mkstemp(prefix=".twinspace-process-", dir=old.parent)
                os.close(fd)
                old.rename(temporary)
                staged.append((old, Path(temporary), target))
            for old, temporary, target in staged:
                temporary.rename(target)
            for old, _, target in staged:
                if old not in targets:
                    old.symlink_to(target.name)
            for plist, data in updates:
                try:
                    plist.write_bytes(plistlib.dumps(data))
                except Exception:
                    pass
        ''') + "PROCESS_NAMES_PY\n"

    @classmethod
    def execute(cls, task: CloneTask, needs_admin: bool = False) -> None:
        """Execute hard clone script.

        Args:
            task: The clone task parameters.
            needs_admin: Whether administrator elevation is required.
        """
        if getattr(task.source, "is_ios_app", False):
            from twinspace.core.i18n import t
            raise CloneError(t("clone_err_ios_wrapper_unsupported"))

        src = shlex.quote(str(task.source.path))
        dst = shlex.quote(str(task.dest_path))

        rel_plist = getattr(task.source, "relative_plist_path", Path("Contents/Info.plist"))
        rel_resources = getattr(task.source, "relative_resources_path", Path("Contents/Resources"))

        dst_plist = shlex.quote(str(task.dest_path / rel_plist))
        dst_resources = shlex.quote(str(task.dest_path / rel_resources))

        # Effective display name: explicit override > clone_name
        effective_display_name = task.display_name if task.display_name else task.clone_name
        display_name_cmd = cls._build_display_name_cmd(effective_display_name, dst_plist, dst_resources)
        icon_cmd = cls._build_icon_cmd(task, dst_resources, dst_plist)
        lsregister_cmd = cls._build_lsregister_cmd(dst)
        dst_parent = shlex.quote(str(task.dest_path.parent))
        orig_bin_name = (
            task.source.executable.name
            if task.source.executable and task.source.executable.name
            else task.source.app_name
        )
        bin_orig = shlex.quote(str(task.dest_path / "Contents" / "MacOS" / orig_bin_name))
        bin_bak = shlex.quote(str(task.dest_path / "Contents" / "MacOS" / f"{orig_bin_name}.bin"))
        wrapper = bin_orig

        lang_env, lang_args = cls._build_language_env_and_args(task)
        valid_launch_args = cls._get_validated_launch_args(task)

        # Fallback environment isolation if no valid launch args isolate data dir and no env vars are set
        effective_env = dict(task.recipe.environment_injection)
        # Keep pre-3.0 ATB_* recipe overrides working alongside the new names
        # (mirrors _resolve_env so hard clones detect isolation keys too).
        for key, value in list(effective_env.items()):
            if key.startswith("ATB_"):
                effective_env.setdefault("TWINSPACE_" + key[4:], value)
        has_data_in_args = any(
            "{{TWINSPACE_DATA_DIR}}" in arg or "{{TWINSPACE_ENV_DIR}}" in arg
            for arg in valid_launch_args
        )
        has_data_in_env = any(
            "{{TWINSPACE_DATA_DIR}}" in value
            or "{{TWINSPACE_ENV_DIR}}" in value
            or "{{ATB_DATA_DIR}}" in value
            or "{{ATB_ENV_DIR}}" in value
            for value in effective_env.values()
        )
        if not has_data_in_args and not has_data_in_env:
            effective_env["HOME"] = "{{TWINSPACE_DATA_DIR}}/Home"
            effective_env["TMPDIR"] = "{{TWINSPACE_DATA_DIR}}/Tmp"

        effective_env = {
            key: cls._resolve_template(value, task)
            for key, value in effective_env.items()
        }
        needs_isolation_hook = cls._needs_isolation_hook(effective_env)
        proxy_env = cls._build_proxy_env(task)

        codex_init_cmd = cls._build_codex_init_cmd(task)
        gemini_init_cmd = cls._build_gemini_init_cmd(task)
        claude_init_cmd = cls._build_claude_init_cmd(task)

        # Inject launch_args (e.g. --user-data-dir=... for Chromium apps)
        args_list = cls._combine_launch_args(valid_launch_args, lang_args, task)

        symlink_snippet = cls._build_symlink_whitelist_snippet(task)
        pref_seeding = cls._build_preference_seeding_snippet(task)

        app_type = getattr(task.recipe, "app_type", None)
        if not app_type and hasattr(task, "source") and task.source and getattr(task.source, "path", None):
            from twinspace.core.app_prober import AppProber
            app_type = AppProber.detect_app_type(
                task.source.path,
                bundle_id=getattr(task.source, "bundle_id", ""),
            )
        is_chromium = (app_type or "").lower() in ("chromium", "electron")

        strategy_pref = getattr(task, "injection_strategy", None) or getattr(task.recipe, "injection_strategy", "auto")
        strategy_pref = strategy_pref.lower() if strategy_pref else "auto"

        use_dylib = False
        source_bin = getattr(task.source, "executable", None)

        is_lark = (
            getattr(task.recipe, "patch_lark_isolation", False)
            or getattr(task.source, "bundle_id", "") == "com.electron.lark"
            or getattr(task, "new_bundle_id", "").startswith("com.electron.lark")
        )
        is_chatgpt = (
            getattr(task.recipe, "patch_chatgpt_isolation", False)
            or getattr(task.source, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
            or getattr(task.recipe, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
            or getattr(task, "new_bundle_id", "").startswith("com.openai.codex")
            or getattr(task, "new_bundle_id", "").startswith("com.openai.chat")
        )

        if needs_isolation_hook and strategy_pref == "dylib":
            logger.warning(
                "Isolation hook (keychain/browser/OAuth) requires the native launcher; "
                "overriding dylib injection strategy."
            )
        if needs_isolation_hook or is_lark or is_chatgpt:
            use_dylib = False
        elif strategy_pref == "launcher":
            use_dylib = False
        elif strategy_pref == "dylib":
            # Explicit dylib requested: if source_bin exists, verify headroom
            if source_bin and source_bin.exists():
                safe, reason = cls._check_macho_injection_headroom(source_bin)
                if not safe:
                    raise CloneError(f"Mach-O dylib injection failed: {reason}")
            use_dylib = True
        else:  # "auto"
            if not is_chromium and not valid_launch_args:
                if source_bin:
                    safe, reason = cls._check_macho_injection_headroom(source_bin)
                else:
                    safe, reason = False, "source executable unavailable"
                if safe:
                    use_dylib = True
                else:
                    logger.warning(
                        f"Mach-O dylib injection not verified ({reason}); "
                        "falling back to native C launcher."
                    )
                    use_dylib = False
            else:
                use_dylib = False

        task.actual_injection_strategy = "dylib" if use_dylib else "launcher"

        if use_dylib:
            dst_frameworks = shlex.quote(str(task.dest_path / "Contents" / "Frameworks"))
            exec_prep_cmd = cls._build_dylib_env_cmd(
                dst_frameworks=dst_frameworks,
                effective_env=effective_env,
                proxy_env=proxy_env,
                lang_env=lang_env,
                data_dir=task.data_dir,
                bin_orig=bin_orig,
            )
        else:
            orig_bin_c = _escape_c_string(orig_bin_name).replace("%", "%%")
            target_bin_statement = f"""    char exec_path[PATH_MAX];
    uint32_t size = sizeof(exec_path);
    if (_NSGetExecutablePath(exec_path, &size) != 0) {{
        return 1;
    }}
    char *dir = dirname(exec_path);
    char real_bin[PATH_MAX];
    snprintf(real_bin, sizeof(real_bin), "%s/{orig_bin_c}.bin", dir);"""

            is_chatgpt = (
                getattr(task.recipe, "patch_chatgpt_isolation", False)
                or getattr(task.source, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
                or getattr(task.recipe, "bundle_id", "") in ("com.openai.codex", "com.openai.chat")
                or getattr(task, "new_bundle_id", "").startswith("com.openai.codex")
                or getattr(task, "new_bundle_id", "").startswith("com.openai.chat")
            )
            if is_lark:
                hook_dylib_rel_path = "../Frameworks/libtwinspace_lark_hook.dylib"
            elif is_chatgpt:
                hook_dylib_rel_path = "../Frameworks/libtwinspace_chatgpt_hook.dylib"
            else:
                hook_dylib_rel_path = ""

            extra_hook_paths = (
                ["../Frameworks/libtwinspace_isolation.dylib"]
                if needs_isolation_hook
                else []
            )
            c_launcher_cmd = cls._build_c_launcher_compile_cmd(
                dst_wrapper=wrapper,
                target_bin_statement=target_bin_statement,
                effective_env=effective_env,
                proxy_env=proxy_env,
                lang_env=lang_env,
                args_list=args_list,
                data_dir=task.data_dir,
                hook_dylib_rel_path=hook_dylib_rel_path,
                extra_hook_dylib_rel_paths=extra_hook_paths,
            )
            exec_prep_cmd = f"mv {bin_orig} {bin_bak}\n{c_launcher_cmd}"

        # Build framework singleton patcher command ONLY when explicitly enabled by recipe
        # and NOT for Feishu/Lark or ChatGPT which use dedicated Cocoa/POSIX hook isolation.
        needs_singleton_patch = (
            getattr(task.recipe, "patch_framework_singleton", False)
            and not is_lark
            and not is_chatgpt
        )
        singleton_patch_cmd = (
            cls._build_singleton_patch_cmd(task.dest_path)
            if needs_singleton_patch
            else ""
        )

        # Build CEF patcher command ONLY when explicitly enabled by recipe
        needs_cef_patch = bool(getattr(task.recipe, "patch_cef", False))
        cef_patch_cmd = (
            cls._build_cef_patch_cmd(task.dest_path)
            if needs_cef_patch
            else ""
        )

        # Build Lark isolation command ONLY when cloning Feishu/Lark
        lark_isolation_cmd = (
            cls._build_lark_isolation_cmd(task)
            if is_lark
            else ""
        )

        # Build ChatGPT isolation command ONLY when cloning ChatGPT
        chatgpt_isolation_cmd = (
            cls._build_chatgpt_isolation_cmd(task)
            if is_chatgpt
            else ""
        )

        # Update CFBundleIdentifier for all sub-bundles (.app, .appex, etc.) and clean TeamIdentifier
        orig_id_clean = (
            getattr(task.source, "bundle_id", "")
            if hasattr(task, "source") and task.source
            else getattr(task.recipe, "bundle_id", "")
        )
        helper_bundle_id_cmd = f"""find {dst}/Contents -name "Info.plist" -type f 2>/dev/null | while read -r pfile; do
    /usr/libexec/PlistBuddy -c "Delete :TeamIdentifier" "$pfile" 2>/dev/null || true
    cur_id=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$pfile" 2>/dev/null || true)
    if [ -n "$cur_id" ] && [ "$cur_id" != "{task.new_bundle_id}" ]; then
        if [ -n "{orig_id_clean}" ] && [[ "$cur_id" == *"{orig_id_clean}"* ]]; then
            updated_id="${{cur_id//{orig_id_clean}/{task.new_bundle_id}}}"
            updated_id=$(echo "$updated_id" | sed -E 's/^[A-Z0-9]{{10}}\\.//')
            /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $updated_id" "$pfile" 2>/dev/null || true
        elif [[ "$cur_id" =~ ^[A-Z0-9]{{10}}\\. ]]; then
            new_id=$(echo "$cur_id" | sed -E 's/^[A-Z0-9]{{10}}\\.//')
            /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $new_id.{task.new_bundle_id}" "$pfile" 2>/dev/null || true
        fi
    fi
done
"""

        framework_prune_cmd = cls._build_framework_prune_cmd(task.dest_path)
        process_name_cmd = cls._build_process_name_cmd(
            task, task.dest_path / "Contents/MacOS" / (orig_bin_name if use_dylib else f"{orig_bin_name}.bin"),
        )

        if task.recipe.strip_sandbox:
            codesign_cmds = (
                f'ent_plist=$(mktemp "${{TMPDIR:-/tmp}}/twinspace_ent_XXXXXX")\n'
                f'trap \'rm -f "$ent_plist"\' EXIT INT TERM\n'
                f'codesign -d --entitlements :- --xml {src} > "$ent_plist" 2>/dev/null || codesign -d --entitlements :- {src} > "$ent_plist" 2>/dev/null || true\n'
                f'if [ -s "$ent_plist" ]; then\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.security.app-sandbox" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.security.application-groups" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.team-identifier" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.aps-environment" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.application-identifier" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :keychain-access-groups" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.associated-domains" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.icloud-container-identifiers" "$ent_plist" 2>/dev/null || true\n'
                f'    /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.ubiquity-container-identifiers" "$ent_plist" 2>/dev/null || true\n'
                f'    python3 -c "\n'
                f'import plistlib\n'
                f'try:\n'
                f'    with open(\'$ent_plist\', \'rb\') as fp:\n'
                f'        pl = plistlib.load(fp)\n'
                f'    restricted = (\'com.apple.developer.\', \'com.apple.application-identifier\', \'keychain-access-groups\', \'com.apple.security.application-groups\', \'com.apple.security.app-sandbox\')\n'
                f'    filtered = {{k: v for k, v in pl.items() if not any(k.startswith(p) for p in restricted)}}\n'
                f'    with open(\'$ent_plist\', \'wb\') as fp:\n'
                f'        plistlib.dump(filtered, fp)\n'
                f'except Exception:\n'
                f'    pass\n'
                f'" 2>/dev/null || true\n'
                f'    find {dst} -type f \\( -name \'*.dylib\' -o -name \'*.so\' \\) -exec codesign --force --sign - {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -type f -perm +111 | while read -r bin_file; do if file "$bin_file" 2>/dev/null | grep -q \'Mach-O\'; then codesign --force --sign - --entitlements "$ent_plist" "$bin_file" 2>/dev/null || true; fi; done\n'
                f'    find {dst}/Contents -name \'*.framework\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -name \'*.appex\' -type d -exec codesign --force --deep --sign - --entitlements "$ent_plist" {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -name \'*.app\' -type d -exec codesign --force --deep --sign - --entitlements "$ent_plist" {{}} + 2>/dev/null || true\n'
                f'    codesign --force --deep --sign - --entitlements "$ent_plist" {dst}\n'
                f'else\n'
                f'    find {dst} -type f \\( -name \'*.dylib\' -o -name \'*.so\' \\) -exec codesign --force --sign - {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -type f -perm +111 | while read -r bin_file; do if file "$bin_file" 2>/dev/null | grep -q \'Mach-O\'; then codesign --force --sign - "$bin_file" 2>/dev/null || true; fi; done\n'
                f'    find {dst}/Contents -name \'*.framework\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -name \'*.appex\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'    find {dst}/Contents -name \'*.app\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'    codesign --force --deep --sign - {dst}\n'
                f'fi\n'
                f'rm -f "$ent_plist"\n'
            )
        else:
            codesign_cmds = (
                f'find {dst} -type f \\( -name \'*.dylib\' -o -name \'*.so\' \\) -exec codesign --force --sign - {{}} + 2>/dev/null || true\n'
                f'find {dst}/Contents -type f -perm +111 | while read -r bin_file; do if file "$bin_file" 2>/dev/null | grep -q \'Mach-O\'; then codesign --force --sign - "$bin_file" 2>/dev/null || true; fi; done\n'
                f'find {dst}/Contents -name \'*.framework\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'find {dst}/Contents -name \'*.appex\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'find {dst}/Contents -name \'*.app\' -type d -exec codesign --force --deep --sign - {{}} + 2>/dev/null || true\n'
                f'codesign --force --deep --sign - {dst}\n'
            )

        data_dirs_cmd = cls._build_data_dirs_cmd(task, effective_env)
        isolation_hook_cmd = (
            cls._build_isolation_hook_cmd(task) if needs_isolation_hook else ""
        )

        script = f"""set -e
mkdir -p {dst_parent}
{data_dirs_cmd}
rm -rf {dst}
{codex_init_cmd}{gemini_init_cmd}{claude_init_cmd}cp -Rc {src} {dst} 2>/dev/null || (rm -rf {dst} 2>/dev/null; cp -R {src} {dst})

chmod -R u+w {dst} 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier {task.new_bundle_id}" {dst_plist}
{helper_bundle_id_cmd}{display_name_cmd}
{icon_cmd}{exec_prep_cmd}
{isolation_hook_cmd}
{pref_seeding}
{symlink_snippet}
{singleton_patch_cmd}{cef_patch_cmd}{lark_isolation_cmd}{chatgpt_isolation_cmd}{framework_prune_cmd}{process_name_cmd}xattr -cr {dst} 2>/dev/null || true
{codesign_cmds}codesign -vv --deep --strict {dst}
{lsregister_cmd}
"""

        try:
            Runner.run(script, needs_admin)
        except Exception:
            try:
                Runner.run(f"rm -rf {dst}", needs_admin)
            except (CloneError, OSError):
                pass
            raise

