## What and why

## Official source for any API/packaging claim

## Tests
- [ ] The four gates ran bare and green locally (`ruff check`, `ruff format --check`, `mypy`, `pytest -m "not integration"`)
- [ ] New behaviour has a test that fails without the change
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

## Security
- [ ] No order gate weakened; no tool declares order execution; no credential or account id in the diff
