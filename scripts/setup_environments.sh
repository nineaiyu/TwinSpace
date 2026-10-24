#!/usr/bin/env bash
# Create one fully isolated ZCode + WorkBuddy + Chrome environment per name.
#
# Usage:
#   scripts/setup_environments.sh phone1 phone2 phone3 phone4 phone5
#
# Optional overrides:
#   ZCODE_APP=/path/to/ZCode.app
#   WORKBUDDY_APP=/path/to/WorkBuddy.app
#   CODEBUDDY_APP=/path/to/CodeBuddy CN.app
#   QODER_APP=/path/to/Qoder CN.app
#   TRAE_APP=/path/to/Trae CN.app
#   CHROME_APP=/path/to/Google Chrome.app
#   TWINSPACE_BIN=/path/to/twinspace
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "usage: $0 <environment-name> [environment-name ...]" >&2
    exit 2
fi

reject_path_components() {
    local value="$1"
    if [[ -z "$value" || "$value" == */* || "$value" == "." || "$value" == ".." ]]; then
        echo "invalid environment name: $value" >&2
        exit 2
    fi
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
zcode_app="${ZCODE_APP:-/Applications/ZCode.app}"
workbuddy_app="${WORKBUDDY_APP:-/Applications/WorkBuddy.app}"
codebuddy_app="${CODEBUDDY_APP:-/Applications/CodeBuddy CN.app}"
qoder_app="${QODER_APP:-/Applications/Qoder CN.app}"
trae_app="${TRAE_APP:-/Applications/Trae CN.app}"
chrome_app="${CHROME_APP:-/Applications/Google Chrome.app}"

if [[ ! -d "$chrome_app" ]]; then
    echo "missing Chrome app bundle: $chrome_app" >&2
    exit 1
fi

if [[ -n "${TWINSPACE_BIN:-}" ]]; then
    twinspace_cmd=("$TWINSPACE_BIN")
elif command -v twinspace >/dev/null 2>&1; then
    twinspace_cmd=(twinspace)
elif [[ -x "$repo_root/.venv/bin/twinspace" ]]; then
    twinspace_cmd=("$repo_root/.venv/bin/twinspace")
else
    twinspace_cmd=(python3 -m twinspace)
fi

apps_dir="${TWINSPACE_APPS_DIR:-$HOME/TwinSpace/Apps}"
data_root="${TWINSPACE_DATA_DIR:-$HOME/TwinSpace/Data}"

for env_name in "$@"; do
    reject_path_components "$env_name"
    env_data="$data_root/Environments/$env_name"
    chrome_clone="$apps_dir/Chrome-$env_name.app"

    echo "==> environment: $env_name ($env_data)"

    if [[ -d "$chrome_clone" ]]; then
        echo "    Chrome clone exists, skipping: $chrome_clone"
    else
        # Chrome owns <env>/Browser; every app clone is pointed at this exact
        # profile so its external links and OAuth windows use this env's cookies.
        "${twinspace_cmd[@]}" clone "$chrome_app" \
            --name "Chrome-$env_name" \
            --output-dir "$apps_dir" \
            --env-group "$env_name" \
            --data-dir "$env_data/Browser"
    fi

    app_specs=(
        "ZCode|$zcode_app"
        "WorkBuddy|$workbuddy_app"
        "CodeBuddy|$codebuddy_app"
        "Qoder|$qoder_app"
        "Trae|$trae_app"
    )
    for spec in "${app_specs[@]}"; do
        short_name="${spec%%|*}"
        app_path="${spec#*|}"
        clone_app="$apps_dir/$short_name-$env_name.app"

        if [[ ! -d "$app_path" ]]; then
            echo "    $short_name source app not found, skipping: $app_path"
            continue
        fi
        if [[ -d "$clone_app" ]]; then
            echo "    $short_name clone exists, skipping: $clone_app"
            continue
        fi

        "${twinspace_cmd[@]}" clone "$app_path" \
            --name "$short_name-$env_name" \
            --output-dir "$apps_dir" \
            --env-group "$env_name" \
            --data-dir "$env_data/$short_name-$env_name" \
            --set-env "TWINSPACE_BROWSER_APP_PATH=$chrome_clone"
    done

    echo "    done: $chrome_clone + apps under $env_data"
done
