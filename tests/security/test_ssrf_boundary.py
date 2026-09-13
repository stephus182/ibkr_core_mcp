"""Security constitution §5 — every externally derived URL is checked before the fetch and
re-checked on every request the browser makes; the blocked address set is a tested table.

The table below is the probe set from the 2026-09-13 audit
(docs/audits/security-architecture-audit-2026-09-13.md, Invariant 4 / B7). Two rows
document behaviour rather than assert a block: an octal literal (`0177.0.0.1`) resolves to
public 177.0.0.1 in the system resolver while Chromium canonicalises it to 127.0.0.1 — the
browser-level guard sees the canonical URL and aborts, so it is safe on the browser
paths; and `100.64.0.0/10` (RFC 6598 shared address space, which Tailscale uses) was NOT
blocked before this file existed.
"""

from __future__ import annotations

import pytest

from ibkr_core_mcp.local_browser import is_private_host

from .structural import PACKAGE_DIR, call_lines, function_named, functions_calling

pytestmark = pytest.mark.security

CLAUDE_TOOLS = (PACKAGE_DIR / "claude_tools.py").read_text()
LOCAL_BROWSER = (PACKAGE_DIR / "local_browser.py").read_text()

# host literal → must be blocked. Every row needs no DNS: literals are classified locally,
# and the names here are on the guard's own short-circuit list.
BLOCKED_LITERALS = [
    "localhost",
    "localhost.",
    "0.0.0.0",  # noqa: S104 — a blocklist entry, not a bind
    "0",
    "127.0.0.1",
    "127.1",
    "::1",
    "::ffff:127.0.0.1",
    "::ffff:7f00:1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "fe80::1",
    "fd00::1",
    "100.64.0.1",  # RFC 6598 shared address space — Tailscale, CGNAT
    "100.127.255.254",
    "192.0.0.192",
    "2130706433",  # decimal 127.0.0.1
    "0x7f000001",  # hex 127.0.0.1
]


@pytest.mark.parametrize("host", BLOCKED_LITERALS)
def test_the_guard_blocks_every_local_and_reserved_form(host):
    assert is_private_host(host), host


def test_public_literals_are_allowed():
    assert not is_private_host("93.184.216.34")
    assert not is_private_host("2606:2800:220:1:248:1893:25c8:1946")


# ── Every browser-reaching handler validates first ────────────────────────────

BROWSER_ENTRY_CALLS = ("_get_crawl4ai", "crawl_site", "search_site_detailed")


def test_every_handler_that_reaches_the_browser_or_seeder_validates_the_host_first():
    owners = set()
    for callee in BROWSER_ENTRY_CALLS:
        owners |= functions_calling(CLAUDE_TOOLS, callee)
    owners -= {"_get_crawl4ai"}  # the lazy constructor itself
    assert owners == {"_handle_fetch_page", "_handle_crawl_site", "_handle_search_site"}, owners
    for name in owners:
        fn = function_named(CLAUDE_TOOLS, name)
        validate = call_lines(fn, ("_validate_public_url",))
        reach = call_lines(fn, BROWSER_ENTRY_CALLS)
        assert validate and reach and min(validate) < min(reach), f"{name}: browser reached before validation"


def test_both_crawler_entry_points_install_the_per_request_guard():
    """Layer 2: `_install_ssrf_guard` is registered on every browser this module opens."""
    installers = functions_calling(LOCAL_BROWSER, "set_hook")
    assert {"_scrape_one", "_crawl"} <= installers, installers
    assert "_install_ssrf_guard" in LOCAL_BROWSER


# ── search_site: the seeder gets the same per-request layer, on httpx ─────────


def test_the_seeder_hook_refuses_a_private_host_and_passes_a_public_one():
    """Review 2026-09-13: `search_site` validated the bare domain and then handed crawl4ai's
    seeder an unguarded httpx client — every sitemap entry, nested index and `<head>` fetch
    afterwards could target loopback or link-local. httpx runs request hooks on every
    request, redirect hops included, which is the browser paths' layer 2 in httpx form."""
    import asyncio

    import httpx

    from ibkr_core_mcp.local_browser import _reject_private_httpx_request

    with pytest.raises(httpx.RequestError):
        asyncio.run(_reject_private_httpx_request(httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")))
    with pytest.raises(httpx.RequestError):
        asyncio.run(_reject_private_httpx_request(httpx.Request("GET", "http://127.0.0.1:5055/v1/api/tickle")))
    asyncio.run(_reject_private_httpx_request(httpx.Request("GET", "http://93.184.216.34/sitemap.xml")))


def test_search_site_installs_the_seeder_hook():
    seeders = functions_calling(LOCAL_BROWSER, "AsyncUrlSeeder")
    assert "_seed" in seeders, seeders
    import ast

    from .structural import function_named

    seed = ast.unparse(function_named(LOCAL_BROWSER, "_seed"))
    assert "_reject_private_httpx_request" in seed and "event_hooks" in seed


def test_the_ordering_probe_sees_a_late_validation():
    snippet = "def _h(self, inputs):\n    page = self._get_crawl4ai().scrape(inputs['url'])\n    self._validate_public_url(inputs['url'])\n"
    fn = function_named(snippet, "_h")
    assert min(call_lines(fn, BROWSER_ENTRY_CALLS)) < min(call_lines(fn, ("_validate_public_url",)))
