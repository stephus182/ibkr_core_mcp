"""What a consumer may read off a `ClaudeToolkit` — and what it may not (register F29).

claudia_ui read the toolkit's private `_store`, `_config` and `_cache` because `client` was
the only public accessor. A private name carries no compatibility promise, and a consumer's
`MagicMock` toolkits answer to any name, so a rename here would have broken it at startup
with its own suite green. `store` and `config` are public since 2.2.0.

**The Drive cache is not, by the operator's decision (2026-10-01).** A `cache` accessor would
hand a consumer the whole Drive client — uploads, the `store.db` backup, deletes — where the
one consumer that touches it needs two reads of cached bars. If that need is ever served
publicly, it is with a narrow read, not with the object.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ibkr_core_mcp.claude_tools import ClaudeToolkit


@pytest.fixture
def parts():
    """Four distinct collaborators, so a mixed-up accessor is visible."""
    return {name: MagicMock(name=name) for name in ("client", "cache", "store", "config")}


@pytest.fixture
def built(parts):
    """A toolkit built from them — the constructor only stores its four arguments."""
    return ClaudeToolkit(parts["client"], parts["cache"], parts["store"], parts["config"])


@pytest.mark.parametrize("name", ["client", "store", "config"])
def test_a_public_accessor_returns_the_collaborator_the_toolkit_was_built_with(built, parts, name):
    """By identity: the object the caller passed in, not a copy and not its neighbour."""
    assert getattr(built, name) is parts[name]


def test_the_public_surface_of_a_toolkit_is_exactly_this():
    """The whole list, so an accessor added later is a decision, not a drift."""
    public = {name for name in vars(ClaudeToolkit) if not name.startswith("_")}
    assert public == {"client", "store", "config", "tools", "execute"}
