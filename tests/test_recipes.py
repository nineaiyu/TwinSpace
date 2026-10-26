from pathlib import Path

import pytest
from pydantic import ValidationError

from twinspace.recipes import ProxyConfig, Recipe, RecipeLoader


def test_proxy_config_defaults():
    proxy = ProxyConfig()
    assert not proxy.enabled
    assert proxy.type == "http"
    assert proxy.host == "127.0.0.1"
    assert proxy.port == 1080
    assert proxy.username == ""
    assert proxy.password == ""
    assert proxy.no_proxy == "localhost,127.0.0.1,*.local"
    assert proxy.url == "http://127.0.0.1:1080"


def test_proxy_config_with_auth():
    proxy = ProxyConfig(
        enabled=True,
        type="socks5",
        host="proxy.corp.com",
        port=8080,
        username="user1",
        password="secret",
    )
    assert proxy.url == "socks5://user1:secret@proxy.corp.com:8080"


def test_proxy_config_username_only():
    proxy = ProxyConfig(
        enabled=True,
        type="http",
        host="10.0.0.1",
        port=3128,
        username="anonymous",
        password="",
    )
    assert proxy.url == "http://anonymous:@10.0.0.1:3128"


def test_proxy_config_https():
    proxy = ProxyConfig(
        enabled=True,
        type="https",
        host="secure.proxy.com",
        port=8443,
    )
    assert proxy.url == "https://secure.proxy.com:8443"


def test_recipe_defaults():
    recipe = Recipe(
        bundle_id="com.example.app",
        app_name="ExampleApp",
        strategy="hard_clone",
    )
    assert recipe.bundle_id == "com.example.app"
    assert recipe.app_name == "ExampleApp"
    assert recipe.strategy == "hard_clone"
    assert not recipe.strip_sandbox
    assert recipe.proxy.enabled is False
    assert recipe.launch_args == []
    assert recipe.app_type is None


def test_recipe_app_type_field():
    recipe = Recipe(
        bundle_id="com.google.Chrome",
        app_name="Chrome",
        strategy="soft_clone",
        app_type="chromium",
    )
    assert recipe.app_type == "chromium"

    recipe_cocoa = Recipe(
        bundle_id="com.tencent.xinWeChat",
        app_name="WeChat",
        strategy="hard_clone",
        app_type="cocoa",
    )
    assert recipe_cocoa.app_type == "cocoa"


def test_chromium_recipes_support_hard_and_soft_clone():
    for bid in [
        "com.google.Chrome",
        "org.chromium.Chromium",
        "com.microsoft.edgemac",
        "company.thebrowser.Browser",
    ]:
        recipe_hard = Recipe(
            bundle_id=bid,
            app_name="Browser",
            strategy="hard_clone",
        )
        assert recipe_hard.strategy == "hard_clone"

        recipe_soft = Recipe(
            bundle_id=bid,
            app_name="Browser",
            strategy="soft_clone",
        )
        assert recipe_soft.strategy == "soft_clone"



def test_recipe_invalid_strategy():
    with pytest.raises(ValidationError):
        Recipe(
            bundle_id="com.example.app",
            app_name="ExampleApp",
            strategy="invalid_strategy",  # type: ignore
        )


def test_load_builtin_wechat():
    recipe = RecipeLoader.match("com.tencent.xinWeChat")
    assert recipe is not None
    assert recipe.bundle_id == "com.tencent.xinWeChat"
    assert recipe.app_name == "微信"
    assert recipe.strategy == "hard_clone"
    assert recipe.strip_sandbox is True
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection
    assert "Library/Keychains" in recipe.symlink_whitelist
    assert ".ssh" in recipe.symlink_whitelist


def test_load_builtin_chrome():
    recipe = RecipeLoader.match("com.google.Chrome")
    assert recipe is not None
    assert recipe.bundle_id == "com.google.Chrome"
    assert recipe.strategy == "soft_clone"
    assert any("--user-data-dir" in arg for arg in recipe.launch_args)


def test_load_fallback_unknown():
    recipe = RecipeLoader.match("com.unknown.app")
    assert recipe is not None
    assert recipe.bundle_id == "com.unknown.app"
    assert recipe.app_name == "Unknown"
    assert recipe.strategy == "hard_clone"


def test_local_recipe_priority(tmp_path, monkeypatch):
    local_dir = tmp_path / "recipes"
    local_dir.mkdir(parents=True)
    custom_yaml = local_dir / "com.tencent.xinWeChat.yaml"
    custom_yaml.write_text(
        """
bundle_id: com.tencent.xinWeChat
app_name: 微信-自定义
strategy: hard_clone
strip_sandbox: true
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(RecipeLoader, "LOCAL_DIR", local_dir)
    recipe = RecipeLoader.match("com.tencent.xinWeChat")
    assert recipe.app_name == "微信-自定义"
    assert recipe.strip_sandbox is True


def test_recipe_loader_get_local_dir_default():
    assert RecipeLoader.LOCAL_DIR is None
    expected = Path.home() / "TwinSpace" / "recipes"
    assert RecipeLoader.get_local_dir() == expected


def test_recipe_loader_load_file_direct(tmp_path):
    custom_file = tmp_path / "custom.yaml"
    custom_file.write_text(
        """
bundle_id: com.custom.tool
app_name: CustomTool
strategy: soft_clone
strip_sandbox: false
launch_args:
  - "--debug"
""",
        encoding="utf-8",
    )
    recipe = RecipeLoader._load_file(custom_file)
    assert recipe.bundle_id == "com.custom.tool"
    assert recipe.app_name == "CustomTool"
    assert recipe.strategy == "soft_clone"
    assert recipe.launch_args == ["--debug"]


def test_load_builtin_qq():
    recipe = RecipeLoader.match("com.tencent.qq")
    assert recipe is not None
    assert recipe.bundle_id == "com.tencent.qq"
    assert recipe.app_name == "QQ"
    assert recipe.strategy == "hard_clone"
    assert recipe.strip_sandbox is True
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection


def test_load_builtin_wework(monkeypatch, tmp_path):
    monkeypatch.setattr(RecipeLoader, "LOCAL_DIR", tmp_path)
    recipe = RecipeLoader.match("com.tencent.WeWorkMac")
    assert recipe is not None
    assert recipe.bundle_id == "com.tencent.WeWorkMac"
    assert recipe.app_name == "企业微信"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "chromium"
    assert recipe.strip_sandbox is True
    assert recipe.injection_strategy == "dylib"
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection
    assert "Library/Keychains" in recipe.symlink_whitelist


def test_load_builtin_kakaotalk(monkeypatch, tmp_path):
    """Load the built-in KakaoTalk settings without relying on local overrides."""
    monkeypatch.setattr(RecipeLoader, "LOCAL_DIR", tmp_path)
    recipe = RecipeLoader.get("com.kakao.KakaoTalkMac")
    assert recipe is not None
    assert recipe.bundle_id == "com.kakao.KakaoTalkMac"
    assert recipe.app_name == "KakaoTalk"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "cocoa"
    assert recipe.strip_sandbox is True
    assert recipe.injection_strategy == "auto"
    assert recipe.environment_injection == {
        "HOME": "{{TWINSPACE_DATA_DIR}}/Home",
        "TMPDIR": "{{TWINSPACE_DATA_DIR}}/Tmp",
    }
    assert recipe.proxy.enabled is False
    assert recipe.launch_args == []


def test_load_builtin_chatgpt():
    recipe = RecipeLoader.match("com.openai.codex")
    assert recipe is not None
    assert recipe.bundle_id == "com.openai.codex"
    assert recipe.app_name == "ChatGPT"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.strip_sandbox is True
    assert recipe.patch_chatgpt_isolation is True
    assert recipe.strip_url_schemes is True
    assert recipe.patch_framework_singleton is False
    assert recipe.launch_args == []
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection
    assert recipe.environment_injection.get("CODEX_HOME") == "{{TWINSPACE_DATA_DIR}}/Codex"


def test_load_builtin_chatgpt_chat():
    recipe = RecipeLoader.match("com.openai.chat")
    assert recipe is not None
    assert recipe.bundle_id == "com.openai.chat"
    assert recipe.app_name == "ChatGPT"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.strip_sandbox is True
    assert recipe.patch_chatgpt_isolation is True
    assert recipe.strip_url_schemes is True
    assert recipe.patch_framework_singleton is False
    assert recipe.launch_args == []
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection
    assert recipe.environment_injection.get("CODEX_HOME") == "{{TWINSPACE_DATA_DIR}}/Codex"


def test_load_builtin_claude():
    recipe = RecipeLoader.match("com.anthropic.claudefordesktop")
    assert recipe is not None
    assert recipe.bundle_id == "com.anthropic.claudefordesktop"
    assert "HOME" in recipe.environment_injection
    assert "TMPDIR" in recipe.environment_injection
    assert recipe.environment_injection.get("CLAUDE_CONFIG_DIR") == "{{TWINSPACE_DATA_DIR}}/Claude"


def test_load_builtin_lark():
    recipe = RecipeLoader.match("com.electron.lark")
    assert recipe is not None
    assert recipe.bundle_id == "com.electron.lark"
    assert recipe.app_name == "飞书"
    assert recipe.strategy == "hard_clone"
    assert recipe.strip_sandbox is True
    assert recipe.patch_lark_isolation is True
    assert recipe.strip_url_schemes is True
    assert recipe.patch_framework_singleton is False
    assert recipe.launch_args == []
    assert recipe.environment_injection.get("HOME") == "{{TWINSPACE_DATA_DIR}}/Home"
    assert recipe.environment_injection.get("TMPDIR") == "{{TWINSPACE_DATA_DIR}}/Tmp"


def test_load_builtin_zcode_isolation_recipe():
    recipe = RecipeLoader.match("dev.zcode.app")
    assert recipe is not None
    assert recipe.bundle_id == "dev.zcode.app"
    assert recipe.app_name == "ZCode"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.injection_strategy == "launcher"
    assert recipe.seed_preferences is False
    env = recipe.environment_injection
    assert env["ZCODE_DESKTOP_HOME_DIR"] == "{{TWINSPACE_DATA_DIR}}/Home"
    assert env["ZCODE_DESKTOP_USER_DATA_DIR"] == "{{TWINSPACE_DATA_DIR}}/UserData"
    assert env["ZCODE_DESKTOP_SESSION_DATA_DIR"] == "{{TWINSPACE_DATA_DIR}}/Session"
    assert env["TWINSPACE_KEYCHAIN_PREFIX"] == "{{TWINSPACE_KEYCHAIN_PREFIX}}"
    assert env["TWINSPACE_COCOA_HOME_HOOK"] == "1"
    assert env["TWINSPACE_OAUTH_SCHEMES"] == "zcode"
    assert env["TWINSPACE_BROWSER_DATA_DIR"] == "{{TWINSPACE_ENV_DIR}}/Browser"
    assert env["TMPDIR"].endswith("/")
    assert "Library/Keychains" in recipe.symlink_whitelist
    assert "ZCODE_UPDATE_FEED_URL" in env


def test_load_builtin_workbuddy_isolation_recipe():
    recipe = RecipeLoader.match("com.tencent.workbuddy.mac")
    assert recipe is not None
    assert recipe.bundle_id == "com.tencent.workbuddy.mac"
    assert recipe.app_name == "WorkBuddy"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.injection_strategy == "launcher"
    assert recipe.seed_preferences is False
    env = recipe.environment_injection
    assert env["WORKBUDDY_CONFIG_DIR"] == "{{TWINSPACE_DATA_DIR}}/Config"
    assert env["WORKBUDDY_USER_DATA_DIR"] == "{{TWINSPACE_DATA_DIR}}/Config/app"
    assert env["WORKBUDDY_INSTANCE_NUMBER"] == "{{TWINSPACE_INSTANCE_NUMBER}}"
    assert env["WORKBUDDY_DEEPLINK_SCHEMES"] == "workbuddy-{{TWINSPACE_INSTANCE_NUMBER}},buddy-app"
    assert env["TWINSPACE_KEYCHAIN_PREFIX"] == "{{TWINSPACE_KEYCHAIN_PREFIX}}"
    assert "TWINSPACE_KEYCHAIN_EXCLUDE_SERVICES" not in env
    assert env["TWINSPACE_COCOA_HOME_HOOK"] == "1"
    assert env["TWINSPACE_BROWSER_DATA_DIR"] == "{{TWINSPACE_ENV_DIR}}/Browser"
    assert "Library/Keychains" in recipe.symlink_whitelist
    assert "WORKBUDDY_UPDATE_URL" in env


def test_load_builtin_codebuddy_isolation_recipe():
    recipe = RecipeLoader.match("com.tencent.codebuddycn")
    assert recipe is not None
    assert recipe.bundle_id == "com.tencent.codebuddycn"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.injection_strategy == "launcher"
    assert recipe.seed_preferences is False
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}/UserData" in recipe.launch_args
    assert "--extensions-dir={{TWINSPACE_DATA_DIR}}/Extensions" in recipe.launch_args
    assert "--disable-updates" in recipe.launch_args
    assert recipe.environment_injection["TWINSPACE_COCOA_HOME_HOOK"] == "1"
    assert recipe.environment_injection["TWINSPACE_OAUTH_SCHEMES"] == "codebuddycn"
    assert recipe.environment_injection["TWINSPACE_BROWSER_DATA_DIR"] == "{{TWINSPACE_ENV_DIR}}/Browser"
    assert "Library/Keychains" in recipe.symlink_whitelist


def test_load_builtin_qoder_isolation_recipe():
    recipe = RecipeLoader.match("com.qodercn.app")
    assert recipe is not None
    assert recipe.bundle_id == "com.qodercn.app"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.injection_strategy == "launcher"
    assert recipe.seed_preferences is False
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}/UserData" in recipe.launch_args
    assert recipe.environment_injection["QODERCN_CONFIG_DIR"] == "{{TWINSPACE_DATA_DIR}}/Config"
    assert recipe.environment_injection["QODERCN_CLI_HOME"] == "{{TWINSPACE_DATA_DIR}}/CLI"
    assert recipe.environment_injection["TWINSPACE_COCOA_HOME_HOOK"] == "1"
    assert recipe.environment_injection["TWINSPACE_OAUTH_SCHEMES"] == "qoder-cn"
    assert recipe.environment_injection["TWINSPACE_BROWSER_DATA_DIR"] == "{{TWINSPACE_ENV_DIR}}/Browser"
    assert "Library/Keychains" in recipe.symlink_whitelist


def test_load_builtin_trae_isolation_recipe():
    recipe = RecipeLoader.match("cn.trae.app")
    assert recipe is not None
    assert recipe.bundle_id == "cn.trae.app"
    assert recipe.strategy == "hard_clone"
    assert recipe.app_type == "electron"
    assert recipe.injection_strategy == "launcher"
    assert recipe.seed_preferences is False
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}/UserData" in recipe.launch_args
    assert "--extensions-dir={{TWINSPACE_DATA_DIR}}/Extensions" in recipe.launch_args
    assert "--disable-updates" in recipe.launch_args
    assert recipe.environment_injection["TWINSPACE_COCOA_HOME_HOOK"] == "1"
    assert recipe.environment_injection["TWINSPACE_DEVICE_UUID"] == "{{TWINSPACE_DEVICE_UUID}}"
    assert recipe.environment_injection["TWINSPACE_DEVICE_SERIAL"] == "{{TWINSPACE_DEVICE_SERIAL}}"
    assert recipe.environment_injection["TWINSPACE_DEVICE_SEED"] == "{{TWINSPACE_DEVICE_SEED}}"
    assert recipe.environment_injection["TWINSPACE_DEVICE_HOSTNAME"] == "{{TWINSPACE_DEVICE_HOSTNAME}}"
    assert recipe.environment_injection["TWINSPACE_OAUTH_SCHEMES"] == "trae-cn"
    assert recipe.environment_injection["TWINSPACE_BROWSER_DATA_DIR"] == "{{TWINSPACE_ENV_DIR}}/Browser"
    assert "Library/Keychains" in recipe.symlink_whitelist


def test_load_builtin_chrome_uses_soft_clone_for_keychain_compatibility():
    recipe = RecipeLoader.match("com.google.Chrome")
    assert recipe is not None
    assert recipe.strategy == "soft_clone"
    assert recipe.app_type == "chromium"
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}" in recipe.launch_args


def test_load_builtin_antigravity(monkeypatch, tmp_path):
    monkeypatch.setattr(RecipeLoader, "LOCAL_DIR", tmp_path)
    for bid in ["com.google.antigravity", "com.google.antigravity-ide", "com.google.GeminiMacOS"]:
        recipe = RecipeLoader.match(bid)
        assert recipe is not None
        assert recipe.bundle_id == bid
        assert "HOME" in recipe.environment_injection
        assert "TMPDIR" in recipe.environment_injection
        assert recipe.environment_injection.get("GEMINI_HOME") == "{{TWINSPACE_DATA_DIR}}/Gemini"
        assert recipe.environment_injection.get("GEMINI_CONFIG_DIR") == "{{TWINSPACE_DATA_DIR}}/Gemini"
        assert recipe.environment_injection.get("ANTIGRAVITY_HOME") == "{{TWINSPACE_DATA_DIR}}/Gemini"


def test_load_builtin_edge():
    recipe = RecipeLoader.match("com.microsoft.edgemac")
    assert recipe is not None
    assert recipe.bundle_id == "com.microsoft.edgemac"
    assert recipe.app_name == "Edge"
    assert recipe.strategy == "hard_clone"
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}" in recipe.launch_args


def test_load_builtin_cursor():
    recipe = RecipeLoader.match("com.todesktop.230313mzl4w4u92")
    assert recipe is not None
    assert recipe.bundle_id == "com.todesktop.230313mzl4w4u92"
    assert recipe.app_name == "Cursor"
    assert recipe.strategy == "soft_clone"
    assert "--user-data-dir={{TWINSPACE_DATA_DIR}}" in recipe.launch_args


def test_all_builtin_recipes_valid(monkeypatch, tmp_path):
    monkeypatch.setattr("twinspace.recipes.loader.RecipeLoader.LOCAL_DIR", tmp_path)
    builtin_dir = RecipeLoader.BUILTIN_DIR
    assert builtin_dir.exists()
    yaml_files = list(builtin_dir.glob("*.yaml"))
    # Expecting at least 18 builtin recipes
    assert len(yaml_files) >= 18

    expected_recipes = {
        "com.tencent.xinWeChat": ("微信", "hard_clone", True),
        "com.tencent.WeWorkMac": ("企业微信", "hard_clone", True),
        "com.google.Chrome": ("Chrome", "soft_clone", False),
        "com.tencent.qq": ("QQ", "hard_clone", True),
        "ru.keepcoder.Telegram": ("Telegram", "hard_clone", True),
        "org.telegram.desktop": ("Telegram Desktop", "hard_clone", True),
        "jp.naver.line.mac": ("LINE", "hard_clone", True),
        "com.kakao.KakaoTalkMac": ("KakaoTalk", "hard_clone", True),
        "com.tinyspeck.slackmacgap": ("Slack", "hard_clone", True),
        "com.hnc.Discord": ("Discord", "hard_clone", True),
        "com.skype.skype": ("Skype", "hard_clone", True),
        "com.openai.codex": ("ChatGPT", "hard_clone", True),
        "com.openai.chat": ("ChatGPT", "hard_clone", True),
        "com.anthropic.claudefordesktop": ("Claude", "hard_clone", True),
        "com.google.antigravity": ("Antigravity", "hard_clone", True),
        "com.google.antigravity-ide": ("Antigravity IDE", "hard_clone", True),
        "com.google.GeminiMacOS": ("Gemini", "hard_clone", True),
        "com.microsoft.edgemac": ("Edge", "hard_clone", False),
        "org.mozilla.firefox": ("Firefox", "soft_clone", False),
        "company.thebrowser.Browser": ("Arc", "hard_clone", False),
        "com.todesktop.230313mzl4w4u92": ("Cursor", "soft_clone", False),
        "com.microsoft.VSCode": ("VS Code", "soft_clone", False),
        "dev.zed.Zed": ("Zed", "soft_clone", False),
        "com.electron.lark": ("飞书", "hard_clone", True),
        "com.bilibili.bilibiliPC": ("哔哩哔哩", "hard_clone", True),
        "com.bytedance.douyin.desktop": ("抖音", "hard_clone", True),
        "com.netease.163music": ("网易云音乐", "hard_clone", True),
        "com.valvesoftware.steam": ("Steam", "hard_clone", True),
        "com.kingsoft.wpsoffice.mac": ("WPS Office", "hard_clone", True),
        "com.lemon.lvpro": ("剪映专业版", "hard_clone", True),
        "com.lemon.lvoverseas": ("CapCut", "hard_clone", True),
        "com.google.android.studio": ("Android Studio", "hard_clone", True),
        "com.brave.Browser": ("Brave Browser", "soft_clone", False),
        "org.torproject.torbrowser": ("Tor Browser", "soft_clone", False),
    }

    for bundle_id, (name, strategy, strip_sandbox) in expected_recipes.items():
        recipe = RecipeLoader.match(bundle_id)
        assert recipe.bundle_id == bundle_id
        assert recipe.app_name == name
        assert recipe.strategy == strategy
        assert recipe.strip_sandbox == strip_sandbox


def test_supports_data_dir_with_launch_args():
    from twinspace.recipes.models import Recipe, supports_data_dir

    recipe = Recipe(
        bundle_id="com.google.Chrome",
        app_name="Chrome",
        strategy="hard_clone",
        launch_args=["--user-data-dir={{TWINSPACE_DATA_DIR}}"],
    )
    assert supports_data_dir(recipe) is True


def test_supports_data_dir_with_env_injection():
    from twinspace.recipes.models import Recipe, supports_data_dir

    recipe = Recipe(
        bundle_id="com.tencent.xinWeChat",
        app_name="WeChat",
        strategy="hard_clone",
        environment_injection={"HOME": "{{TWINSPACE_DATA_DIR}}/Home"},
    )
    assert supports_data_dir(recipe) is True


def test_builtin_recipes_have_valid_app_types():
    chrome_recipe = RecipeLoader.get("com.google.Chrome")
    assert chrome_recipe is not None
    assert chrome_recipe.app_type == "chromium"

    vscode_recipe = RecipeLoader.get("com.microsoft.VSCode")
    assert vscode_recipe is not None
    assert vscode_recipe.app_type == "electron"

    firefox_recipe = RecipeLoader.get("org.mozilla.firefox")
    assert firefox_recipe is not None
    assert firefox_recipe.app_type == "firefox"

    wechat_recipe = RecipeLoader.get("com.tencent.xinWeChat")
    assert wechat_recipe is not None
    assert wechat_recipe.app_type == "cocoa"


def test_supports_data_dir_unsupported():
    from twinspace.recipes.models import Recipe, supports_data_dir

    recipe = Recipe(
        bundle_id="dev.zed.Zed",
        app_name="Zed",
        strategy="soft_clone",
        launch_args=[],
        environment_injection={},
    )
    assert supports_data_dir(recipe) is False


def test_all_builtin_recipes_have_explicit_app_type():
    from twinspace.recipes.loader import RecipeLoader
    builtin_dir = RecipeLoader.BUILTIN_DIR
    yaml_files = list(builtin_dir.glob("*.yaml"))
    assert len(yaml_files) >= 30

    missing_app_type = []
    for yf in yaml_files:
        recipe = RecipeLoader._load_file(yf)
        if not recipe.app_type:
            missing_app_type.append(yf.name)

    assert not missing_app_type, f"Builtin recipes missing explicit app_type: {missing_app_type}"


def test_chatgpt_recipes_have_isolation_flags():
    from twinspace.recipes.loader import RecipeLoader

    for bid in ("com.openai.codex", "com.openai.chat"):
        recipe = RecipeLoader.get(bid)
        assert recipe is not None, f"Recipe {bid} should exist"
        assert recipe.patch_chatgpt_isolation is True
        assert recipe.strip_url_schemes is True
        assert recipe.patch_framework_singleton is False
        assert recipe.launch_args == []
        assert "HOME" in recipe.environment_injection







@pytest.mark.parametrize(
    "bundle_id",
    [
        "dev.zcode.app",
        "com.tencent.codebuddycn",
        "com.qodercn.app",
        "com.tencent.workbuddy.mac",
        "cn.trae.app",
    ],
)
def test_environment_recipes_isolate_device_identity(bundle_id):
    recipe = RecipeLoader.match(bundle_id)
    env = recipe.environment_injection
    assert env["TWINSPACE_DEVICE_UUID"] == "{{TWINSPACE_DEVICE_UUID}}"
    assert env["TWINSPACE_DEVICE_SERIAL"] == "{{TWINSPACE_DEVICE_SERIAL}}"
    assert env["TWINSPACE_DEVICE_SEED"] == "{{TWINSPACE_DEVICE_SEED}}"
    assert env["TWINSPACE_DEVICE_HOSTNAME"] == "{{TWINSPACE_DEVICE_HOSTNAME}}"
