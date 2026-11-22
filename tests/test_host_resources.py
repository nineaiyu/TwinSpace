"""Unit tests for host resource mapping (core module, launcher C code, recipe field)."""

from pathlib import Path

import pytest

from twinspace.core.engines import CloneEngine
from twinspace.core.host_resources import (
    CONFIG_KEY,
    HOST_RESOURCE_GROUPS,
    RECOMMENDED_RESOURCE_KEYS,
    RESOURCE_GROUP_ORDER,
    all_managed_paths,
    default_selections,
    expand_entries,
    find_resource_group,
    normalize_selections,
    parse_resource_config,
    render_resources_list,
    sync_resources_list,
    validate_resource_path,
    write_resources_list,
)
from twinspace.executor.runner import CloneError
from twinspace.recipes.models import Recipe


class TestValidateResourcePath:
    def test_accepts_relative_paths(self):
        assert validate_resource_path(".orbstack") == ".orbstack"
        assert validate_resource_path(".config/containers") == ".config/containers"
        assert validate_resource_path(" Library/.ssh ") == "Library/.ssh"

    def test_rejects_absolute_paths(self):
        with pytest.raises(ValueError):
            validate_resource_path("/etc/passwd")
        with pytest.raises(ValueError):
            validate_resource_path("~/orbstk")

    def test_rejects_parent_traversal(self):
        with pytest.raises(ValueError):
            validate_resource_path("../escape")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_resource_path("")


class TestExpandEntries:
    def test_resource_keys_expand_via_catalog(self):
        assert expand_entries(["npm"]) == [".npm"]
        assert expand_entries(["orbstack"]) == [".orbstack", ".docker"]
        assert expand_entries(["shell-rc"]) == [".zshrc", ".zprofile", ".zshenv", ".config/zsh"]

    def test_group_keys_expand_to_whole_group(self):
        expanded = expand_entries(["service"])
        assert expanded == [".orbstack", ".docker", ".colima"]

    def test_entry_order_is_preserved_within_expand(self):
        # expand_entries keeps the caller's order; canonical group ordering is
        # enforced by parse_resource_config (see the nested-selections test).
        expanded = expand_entries(["shell", "config", "cache", "service"])
        assert expanded[:4] == [".zshrc", ".zprofile", ".zshenv", ".config/zsh"]
        assert expanded.index(".zshrc") < expanded.index(".npmrc")
        assert expanded.index(".npm") < expanded.index(".orbstack")

    def test_duplicates_are_removed_preserving_order(self):
        assert expand_entries(["orbstack", "docker"]) == [".orbstack", ".docker"]
        assert expand_entries(["docker", "orbstack"]) == [".docker", ".orbstack"]

    def test_raw_paths_pass_through(self):
        assert expand_entries([".kube"]) == [".kube"]
        assert expand_entries(["npm", ".kube"]) == [".npm", ".kube"]

    def test_invalid_entry_raises(self):
        with pytest.raises(ValueError):
            expand_entries(["../escape"])

    def test_blank_entries_are_ignored(self):
        assert expand_entries(["", "  "]) == []


class TestFindResourceGroup:
    def test_resource_keys_map_to_groups(self):
        assert find_resource_group("orbstack") == "service"
        assert find_resource_group("npm") == "cache"
        assert find_resource_group("ssh") == "config"
        assert find_resource_group("nvm") == "shell"

    def test_group_keys_and_unknown_keys(self):
        assert find_resource_group("cache") == "cache"
        assert find_resource_group("nope") is None


class TestAllManagedPaths:
    def test_union_covers_every_catalog_entry(self):
        managed = all_managed_paths()
        for group in RESOURCE_GROUP_ORDER:
            for candidates in HOST_RESOURCE_GROUPS[group].values():
                for candidate in candidates:
                    assert candidate in managed


class TestNormalizeSelections:
    def test_malformed_values_become_empty(self):
        assert normalize_selections(None) == {group: [] for group in RESOURCE_GROUP_ORDER}
        assert normalize_selections("service") == {group: [] for group in RESOURCE_GROUP_ORDER}

    def test_string_items_are_coerced_and_ordered(self):
        normalized = normalize_selections({"cache": ["npm"], "service": "orbstack", "bogus": ["x"]})
        assert normalized["cache"] == ["npm"]
        assert normalized["service"] == ["orbstack"]
        assert normalized["config"] == []
        assert normalized["shell"] == []


class TestParseResourceConfig:
    def test_missing_config_falls_back_to_recommended_defaults(self):
        paths = parse_resource_config({})
        # Recommended: everything except the credential-heavy trio.
        assert ".npm" in paths
        assert "Library/Caches/pip" in paths
        assert ".orbstack" in paths
        assert ".colima" in paths
        assert ".npmrc" in paths
        assert ".zshrc" in paths
        assert ".cargo" in paths
        assert ".rustup" in paths
        assert ".nvm" in paths
        # Sensitive credentials stay opt-in.
        assert ".ssh" not in paths
        assert ".netrc" not in paths
        assert ".kube" not in paths

    def test_explicit_disabled_yields_empty(self):
        assert parse_resource_config({CONFIG_KEY: {"enabled": False, "selections": {"cache": ["npm"]}}}) == []
        assert parse_resource_config({CONFIG_KEY: {"enabled": False, "selections": {}}}) == []

    def test_explicit_partial_selection_respected_exactly(self):
        cfg = {CONFIG_KEY: {"enabled": True, "selections": {"cache": ["npm"]}}}
        assert parse_resource_config(cfg) == [".npm"]

    def test_default_selections_shape(self):
        selections = default_selections()
        assert set(selections) == set(RESOURCE_GROUP_ORDER)
        flat = {key for keys in selections.values() for key in keys}
        assert flat == set(RECOMMENDED_RESOURCE_KEYS)

    def test_none_loads_from_disk(self, monkeypatch):
        monkeypatch.setattr(
            "twinspace.core.config.load_config",
            lambda: {CONFIG_KEY: {"enabled": True, "selections": {"cache": ["npm"]}}},
        )
        assert parse_resource_config(None) == [".npm"]

    def test_nested_selections_expand_in_group_order(self):
        cfg = {
            CONFIG_KEY: {
                "enabled": True,
                "selections": {
                    "shell": ["shell-rc"],
                    "config": ["npmrc"],
                    "cache": ["npm", "pip"],
                    "service": ["orbstack"],
                },
            }
        }
        paths = parse_resource_config(cfg)
        # Groups land in canonical order; .docker dedupes across orbstack/docker.
        assert paths == [
            ".orbstack",
            ".docker",
            ".npm",
            "Library/Caches/pip",
            ".cache/pip",
            ".npmrc",
            ".zshrc",
            ".zprofile",
            ".zshenv",
            ".config/zsh",
        ]

    def test_invalid_selection_raises(self):
        cfg = {CONFIG_KEY: {"enabled": True, "selections": {"cache": ["../oops"]}}}
        with pytest.raises(ValueError):
            parse_resource_config(cfg)


class TestResourcesListFile:
    def test_render_includes_paths_and_header(self):
        content = render_resources_list([".orbstack", ".npm"])
        assert content.startswith("#")
        assert ".orbstack\n" in content
        assert ".npm\n" in content

    def test_write_and_list_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("twinspace.core.config.get_base_dir", lambda: tmp_path)
        target = write_resources_list([".npm"])
        assert target == tmp_path / "HostResources.list"
        assert ".npm" in target.read_text(encoding="utf-8").splitlines()

    def test_sync_reads_config_when_not_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr("twinspace.core.config.get_base_dir", lambda: tmp_path)
        monkeypatch.setattr(
            "twinspace.core.config.load_config",
            lambda: {CONFIG_KEY: {"enabled": True, "selections": {"cache": ["npm"]}}},
        )
        written = sync_resources_list()
        lines = written.read_text(encoding="utf-8").splitlines()
        assert ".npm" in lines
        assert ".orbstack" not in lines

    def test_sync_with_disabled_config_writes_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr("twinspace.core.config.get_base_dir", lambda: tmp_path)
        monkeypatch.setattr(
            "twinspace.core.config.load_config",
            lambda: {CONFIG_KEY: {"enabled": False, "selections": {"cache": ["npm"]}}},
        )
        written = sync_resources_list()
        content = written.read_text(encoding="utf-8")
        assert ".npm" not in content


class TestHostResourceCCode:
    def test_render_contains_helpers_and_arrays(self):
        definition, call = CloneEngine._render_host_resource_c_code(
            baked_extra=[".orbstack"],
            managed_union=[".orbstack", ".npm", ".zshrc"],
            base_dir="/Users/test/TwinSpace",
        )
        assert "static void twinspace_ensure_host_resources(void)" in definition
        assert "static void twinspace_resource_ensure_one(" in definition
        assert '".orbstack"' in definition
        assert '".npm"' in definition
        assert "const int ts_baked_count = 1;" in definition
        assert "const int ts_managed_count = 3;" in definition
        assert "/Users/test/TwinSpace" in definition
        assert "HostResources.list" in definition
        assert call == "    twinspace_ensure_host_resources();"

    def test_render_with_empty_lists_is_still_valid_c(self):
        definition, _ = CloneEngine._render_host_resource_c_code([], [], "/tmp")
        assert "static const char *ts_managed[] = {NULL};" in definition
        assert "const int ts_managed_count = 0;" in definition

    def test_launcher_embeds_resource_call(self):
        cmd = CloneEngine._build_c_launcher_compile_cmd(
            dst_wrapper="/dst/app",
            target_bin_statement='    char *real_bin = "/bin/x";',
            effective_env={"HOME": "/data/Home"},
            proxy_env="",
            lang_env="",
            args_list=[],
            data_dir=Path("/data"),
            host_resource_code=(
                "static void twinspace_ensure_host_resources(void) {}",
                "    twinspace_ensure_host_resources();",
            ),
        )
        assert "#include <sys/stat.h>" in cmd
        assert "static void twinspace_ensure_host_resources(void)" in cmd
        # The call must run after the environment block and before execv.
        assert cmd.index("twinspace_ensure_host_resources();") < cmd.index("execv(real_bin")

    def test_launcher_without_resource_code_has_no_call(self):
        cmd = CloneEngine._build_c_launcher_compile_cmd(
            dst_wrapper="/dst/app",
            target_bin_statement='    char *real_bin = "/bin/x";',
            effective_env={},
            proxy_env="",
            lang_env="",
            args_list=[],
            data_dir=Path("/data"),
        )
        assert "twinspace_ensure_host_resources();" not in cmd

    def test_dylib_embeds_resource_call_in_constructor(self):
        cmd = CloneEngine._build_dylib_env_cmd(
            dst_frameworks="/dst/Frameworks",
            effective_env={"HOME": "/data/Home"},
            proxy_env="",
            lang_env="",
            data_dir=Path("/data"),
            bin_orig="'/dst/Contents/MacOS/App.bin'",
            host_resource_code=(
                "static void twinspace_ensure_host_resources(void) {}",
                "    twinspace_ensure_host_resources();",
            ),
        )
        assert "#include <sys/stat.h>" in cmd
        assert "static void twinspace_ensure_host_resources(void)" in cmd
        constructor_pos = cmd.index("static void twinspace_env_init(void)")
        call_pos = cmd.index("twinspace_ensure_host_resources();", constructor_pos)
        close_pos = cmd.index("}", call_pos)
        assert call_pos < close_pos

    def test_baked_code_path_from_recipe(self, monkeypatch):
        monkeypatch.setattr(
            "twinspace.core.config.get_base_dir", lambda: Path("/Users/test/TwinSpace")
        )
        recipe = Recipe(
            bundle_id="com.example.testapp",
            app_name="TestApp",
            strategy="hard_clone",
            host_resources=["npm", ".kube"],
        )
        definition, _ = CloneEngine._build_host_resource_code(
            __import__("types").SimpleNamespace(recipe=recipe)
        )
        assert '".npm"' in definition
        assert '".kube"' in definition
        assert "const int ts_baked_count = 2;" in definition

    def test_group_key_in_recipe_expands(self, monkeypatch):
        monkeypatch.setattr(
            "twinspace.core.config.get_base_dir", lambda: Path("/Users/test/TwinSpace")
        )
        recipe = Recipe(
            bundle_id="com.example.testapp",
            app_name="TestApp",
            strategy="hard_clone",
            host_resources=["service"],
        )
        definition, _ = CloneEngine._build_host_resource_code(
            __import__("types").SimpleNamespace(recipe=recipe)
        )
        assert '".orbstack"' in definition
        assert '".colima"' in definition

    def test_invalid_recipe_entry_raises_clone_error(self):
        from types import SimpleNamespace

        # model_construct skips validators: the engine must still defend against
        # entries that bypassed recipe validation.
        recipe = Recipe.model_construct(
            bundle_id="com.example.testapp",
            app_name="TestApp",
            strategy="hard_clone",
            host_resources=["../escape"],
        )
        with pytest.raises(CloneError):
            CloneEngine._build_host_resource_code(SimpleNamespace(recipe=recipe))


class TestRecipeHostResourcesField:
    def _recipe(self, **overrides) -> Recipe:
        return Recipe(
            bundle_id="com.example.testapp",
            app_name="TestApp",
            strategy="hard_clone",
            **overrides,
        )

    def test_default_is_empty(self):
        assert self._recipe().host_resources == []

    def test_accepts_relative_paths(self):
        recipe = self._recipe(host_resources=["npm", ".kube"])
        assert recipe.host_resources == ["npm", ".kube"]

    def test_rejects_absolute_and_traversal(self):
        with pytest.raises(ValueError):
            self._recipe(host_resources=["/etc"])
        with pytest.raises(ValueError):
            self._recipe(host_resources=["../up"])
