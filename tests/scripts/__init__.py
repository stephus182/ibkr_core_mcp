"""Tests for the operational CLIs under `scripts/`.

These four scripts had **zero** test coverage until 2026-08-10, which is the direct
cause of the defect class the 2026-08-07 Flex audit found: every one of them ended in an
unconditional `return 0`, and nothing ever executed them to notice.

They are importable here as bare module names because `pyproject.toml` puts `scripts/`
on pytest's `pythonpath`; `scripts/` deliberately stays a plain directory rather than a
package, since the files are entry points rather than library code.
"""
