# Contributing to TwinSpace

Thanks for taking the time to improve TwinSpace. This project targets macOS and
is written in Python 3.12+ with a BeeWare/Toga GUI and a Click CLI.

## Development setup

```bash
git clone https://github.com/nineaiyu/TwinSpace.git
cd TwinSpace
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gui]"
```

Run the test suite and the GUI:

```bash
PYTHONPATH=src python -m pytest -q
bash scripts/run_gui.sh
```

Most integration tests require macOS because the cloning engine uses
`codesign`, `PlistBuddy`, Keychain APIs and Mach-O inspection.

## Branching and commits

- Create a topic branch from `main`; do not commit directly to `main`.
- Keep commits focused. Use Conventional Commit prefixes such as `feat:`, `fix:`,
  `refactor:`, `docs:`, `test:` and `chore:`.
- Include tests for behavior changes. A change that affects cloning, Keychain,
  browser routing or environment data must have regression coverage.
- Do not commit credentials, Apple signing certificates, `.env` files, generated
  DMGs or local clone data.

## Code layout

- `src/twinspace/core/` — macOS cloning engine, state, Keychain, recipes and
  environment orchestration. This layer must not import Toga.
- `src/twinspace/cli/` — Click commands. Reuse the core managers instead of
  duplicating cloning logic.
- `src/twinspace/gui/` — BeeWare/Toga views and async adapters.
- `src/twinspace/recipes/builtin/` — bundled application recipes.
- `tests/` — pytest coverage, including GUI smoke tests and shell-script checks.

## Security expectations

- Treat `clones.yaml` as untrusted input before passing paths to `rm -rf`.
- Keep all interpolated values escaped or validated through `twinspace.validation`.
- Run `codesign --verify --deep --strict` after changing bundle rewriting code.
- Never weaken path validation to make a test pass.

## Packaging and signing

Ad-hoc signing is the default for local builds:

```bash
bash scripts/build_gui.sh --adhoc
```

For distribution, set your own Apple identity and notarization profile:

```bash
export APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export APPLE_TEAM_ID="TEAMID"
bash scripts/build_gui.sh --notarize --profile "notary-profile"
```

The repository intentionally does not contain a team ID, certificate or notary
credentials. Pull requests must not add them.

## Pull requests

Describe the user-visible change, the isolation/security impact, and the tests
you ran. Keep generated artifacts out of the diff. For changes to bundled
recipes, mention the application version you tested.
