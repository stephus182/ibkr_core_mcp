"""Guards that documented defaults match the code.

`.env.example` said `https://localhost:5055` while `Config.from_env` defaulted to
`https://localhost:5055/v1/api`, and `IBKRClient` appends endpoint paths verbatim to
whatever it is given. So copying `.env.example` — the documented way to start —
produced `https://localhost:5055/portfolio/accounts` and every request 404'd. A
wrong default in an example file is a bug with a documentation-shaped disguise.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _env_example_value(key: str) -> str:
    for line in (_REPO / ".env.example").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{key} not found in .env.example")


def test_env_example_gateway_url_matches_the_code_default():
    import inspect

    from ibkr_core_mcp import config as config_mod

    src = inspect.getsource(config_mod.Config.from_env)
    m = re.search(r'os\.environ\.get\(\s*"IBKR_GATEWAY_URL",\s*"([^"]+)"', src)
    assert m, "could not locate the IBKR_GATEWAY_URL default in Config.from_env"
    assert _env_example_value("IBKR_GATEWAY_URL") == m.group(1)


def test_gateway_url_default_carries_the_api_prefix():
    """The specific breakage: paths are appended verbatim, so the prefix is load-bearing."""
    assert _env_example_value("IBKR_GATEWAY_URL").endswith("/v1/api")


def test_readme_documents_the_same_gateway_default():
    readme = (_REPO / "README.md").read_text()
    assert _env_example_value("IBKR_GATEWAY_URL") in readme


def test_readme_tool_count_matches_the_code():
    """README said "42 ready-made Claude AI tools" while TOOL_DEFINITIONS held 44 —
    and README's own line 232 already said 44. Two numbers, one source of truth."""
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    readme = (_REPO / "README.md").read_text()
    claimed = {int(n) for n in re.findall(r"(\d+) ready-made Claude AI tools", readme)}
    assert claimed, "README no longer states a tool count; update or remove this guard"
    assert claimed == {len(TOOL_DEFINITIONS)}, f"README claims {claimed}, code has {len(TOOL_DEFINITIONS)}"
