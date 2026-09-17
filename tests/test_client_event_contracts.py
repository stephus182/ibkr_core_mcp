"""Event Contracts: the request each method builds, pinned against IBKR's own pages.

**These five endpoints have never been executed against a live gateway.** Event contracts
need a subscription the development account does not hold, so there is no captured response
and — by this package's own rule — no model: a model is validated against the wire, never
against a reading of the documentation (`models.py`, and the six models that were wrong for
the package's life behind tests built to match them).

What *is* knowable without a gateway is the request. Every path and query parameter below
was read from the endpoint's API-reference page on 2026-09-17, retrieved alongside a
deliberately fabricated control URL that returned the 508-byte `# Page Not Found` body while
the five real pages returned 5.5-6.8 KB — so the retrieval could fail and did not.

These tests therefore assert the request and stop there. They do not assert response shapes,
because asserting a shape nobody has observed is how `Contract`, `Order`, `Position`,
`Trade`, `Notification` and `AccountSummary` all came to be wrong.

Replaces `get_event_contracts` / `get_event_contract`, which called `/events/contracts` and
`/events/show` — paths absent from IBKR's entire documentation index and non-functional for
every caller, subscribed or not (audit finding API-R4).
"""

from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.exceptions import ConfigError

# Path and query parameters exactly as IBKR's API-reference pages document them.
# The page slug each row came from is the last element, so a reader can re-check it.
DOCUMENTED = [
    ("get_forecast_categories", (), "/forecast/category/tree", None, "get-forecast-categories"),
    ("get_forecast_contract", (12345,), "/forecast/contract/details", {"conid": 12345}, "get-forecast-contract"),
    ("get_forecast_rules", (12345,), "/forecast/contract/rules", {"conid": 12345}, "get-forecast-rules"),
    ("get_forecast_schedules", (12345,), "/forecast/contract/schedules", {"conid": 12345}, "get-forecast-schedule"),
    (
        "get_forecast_market",
        (67890,),
        "/forecast/contract/market",
        {"underlyingConid": 67890},
        "get-forecast-markets",
    ),
]


@pytest.mark.parametrize(("method", "args", "path", "params", "page"), DOCUMENTED)
def test_the_request_matches_the_documented_endpoint(client, method, args, path, params, page):
    """One row per endpoint: the URL and query IBKR's page specifies, and nothing more."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}

    with patch.object(client._session, "get", return_value=response) as sent:
        getattr(client, method)(*args)

    url = sent.call_args.args[0] if sent.call_args.args else sent.call_args.kwargs["url"]
    assert url.endswith(path), f"{method} called {url}, not {path} (see {page}.md)"
    assert sent.call_args.kwargs["params"] == params, f"{method} sent the wrong query (see {page}.md)"


def test_the_optional_exchange_is_omitted_rather_than_sent_empty(client):
    """`exchange` is documented optional and IBKR determines one internally when it is
    absent. Sending `exchange=None` would be a different request from not sending it."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}

    with patch.object(client._session, "get", return_value=response) as sent:
        client.get_forecast_market(67890, exchange="CME")
    assert sent.call_args.kwargs["params"] == {"underlyingConid": 67890, "exchange": "CME"}

    with patch.object(client._session, "get", return_value=response) as sent:
        client.get_forecast_market(67890)
    assert "exchange" not in sent.call_args.kwargs["params"]


@pytest.mark.parametrize("method", ["get_forecast_contract", "get_forecast_rules", "get_forecast_schedules"])
def test_a_non_numeric_conid_is_refused_before_the_network(client, method):
    """Every other conid in `client.py` is validated; these are not an exception just
    because IBKR documents the parameter as a string."""
    with patch.object(client._session, "get") as sent, pytest.raises(ConfigError):
        getattr(client, method)("../../etc/passwd")
    sent.assert_not_called()


def test_the_dead_events_methods_are_gone():
    """`get_event_contracts` / `get_event_contract` called `/events/contracts` and
    `/events/show`. Neither path appears anywhere in IBKR's documentation index, and the
    404 they returned proved nothing on its own — an unentitled account 404s too. They were
    removed rather than repaired, the same treatment `get_regulatory_snapshot` got in
    `6a50f06`. This test exists so they are not reintroduced from an old snippet.
    """
    from ibkr_core_mcp.client import IBKRClient

    for gone in ("get_event_contracts", "get_event_contract"):
        assert not hasattr(IBKRClient, gone), f"{gone} is back; it can only ever raise 404"

    # Checked in the AST, not the text: the comment above the replacement methods explains
    # the removal and necessarily names both dead paths. A substring scan would trip on the
    # prose that documents the rule — the API-12 defect exactly, where a sentence explaining
    # a guard satisfied it.
    import ast
    import pathlib
    import sys

    module_file = sys.modules[IBKRClient.__module__].__file__
    assert module_file is not None, "client.py has no file on disk — the scan would be vacuous"
    tree = ast.parse(pathlib.Path(module_file).read_text())
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/events/")
    }
    assert not literals, f"a dead /events/ path is being requested again: {sorted(literals)}"


FORECAST_METHODS = (
    "get_forecast_categories",
    "get_forecast_contract",
    "get_forecast_market",
    "get_forecast_rules",
    "get_forecast_schedules",
)


def test_the_event_contract_endpoints_stay_marked_unvalidated():
    """The owner's standing position, 2026-09-17, held as a check rather than a comment:

        *"I can open a subscription in the future just for dev purposes but not my priority
        ... assume no live testing, and will be done at some point but expressly NOT
        validated."*

    So this is a **known and accepted** state, not an oversight — and the risk is that it
    stops looking like one. These five methods are indistinguishable from the seventy-odd
    around them that *have* been exercised, and the next reader has no reason to suspect
    otherwise. This test is what tells them.

    Three properties, each with an unlock path rather than a prohibition:

    1. No model return type. A model is validated against a captured response in this
       package; there is no captured response, so there can be no model.
    2. No entry in `tests/fixtures/ibkr_live_shapes.json`. **If one appears, this test
       fails** — which is the point: it means a subscription now exists, and whoever
       captured it should type the responses and move these endpoints into the live suite.
    3. No live test claims to cover them.
    """
    import ast
    import json
    import pathlib
    import sys

    from ibkr_core_mcp.client import IBKRClient

    package = pathlib.Path(sys.modules[IBKRClient.__module__].__file__ or "").parent

    model_names = {
        node.name
        for node in ast.walk(ast.parse((package / "models.py").read_text()))
        if isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id == "IBKRResponse" for b in node.bases)
    }
    client_tree = ast.parse((package / "client.py").read_text())
    typed = {
        node.name
        for node in ast.walk(client_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in FORECAST_METHODS
        and node.returns is not None
        and any(m in ast.unparse(node.returns) for m in model_names)
    }
    assert not typed, (
        f"{sorted(typed)} declare a model return, but no event-contract response has ever been "
        "observed. If a subscription now exists, capture the shapes first — a model built from "
        "documentation is the defect that made all six original models wrong."
    )

    fixture = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ibkr_live_shapes.json").read_text())
    captured = sorted(k for k in fixture if "forecast" in k or "event_contract" in k)
    assert not captured, (
        f"event-contract responses are now captured ({captured}) — the subscription exists. "
        "Type these endpoints against the capture, add live coverage, and delete this test."
    )

    live = (pathlib.Path(__file__).parent / "test_client_live.py").read_text()
    claimed = [m for m in FORECAST_METHODS if m in live]
    assert not claimed, (
        f"the live suite references {claimed}, which cannot run without an event-contract "
        "subscription — a live test that always skips reads as coverage and is not."
    )
