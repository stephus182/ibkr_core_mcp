"""Tests for `ibkr_core_mcp.gateway.preflight` — the read-only readings and the rule.

The readings exist because only one brokerage session exists per username across all IBKR
services, so a needless re-login is what escalates into IB Key challenge/response. Their
whole value is telling those states apart, so each verdict is pinned here.

Moved from the consumer that wrote them (register F45, 2026-11-09) with the imports changed
and nothing weakened: the tests are the specification of the move. Two of the original file's
tests stayed behind (a start-up warning that is the consumer's own word), one went with
`release_session` to the owner's tests, two with the command line to the CLI's. The
`confirm_session` and `gateway_api_url` tests at the end are new: nothing tested the former
directly before (the owner's tests replaced it), and the latter did not exist.
"""

import os
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from ibkr_core_mcp.exceptions import ConfigError
from ibkr_core_mcp.gateway.preflight import (
    EXIT_BORROWED,
    EXIT_CONTESTED,
    EXIT_FREE,
    EXIT_READY,
    EXIT_REFUSED,
    EXIT_UNREACHABLE,
    EXIT_VALIDATING,
    GatewayState,
    LastLogin,
    LoginEvent,
    confirm_session,
    gateway_api_url,
    last_login,
    login_events,
    read_state,
    refine_with_log,
    verdict,
)


def _tickle(**auth):
    """A /tickle response with the given authStatus fields."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "session": "abc",
        "ssoExpires": 600000,
        "collission": auth.pop("collission", False),
        "userId": auth.pop("userId", 99999999),
        "iserver": {"authStatus": {"authenticated": False, "connected": False, "competing": False, **auth}},
    }
    return resp


def test_a_live_session_says_do_not_log_in_again():
    """The one state whose correct action is to do nothing — and the one most likely
    to be overridden out of habit, which is why it is checked first."""
    code, headline, guidance = verdict(GatewayState(reachable=True, authenticated=True, connected=True))
    assert code == EXIT_READY
    assert "do not log in again" in headline.lower()
    assert "escalat" in guidance.lower()


@pytest.mark.parametrize("field", ["competing", "collision"])
def test_a_contested_session_is_reported_before_any_login_advice(field):
    """Another IBKR client holding the session must never read as 'free to log in'."""
    contested: dict[str, Any] = {field: True}
    code, headline, _ = verdict(GatewayState(reachable=True, **contested))
    assert code == EXIT_CONTESTED
    assert "another ibkr client" in headline.lower()


def test_bridge_up_but_unauthenticated_is_its_own_state():
    """connected=True, authenticated=False is the soft-timeout signature, not "no session".

    Measured live 2026-08-05: `ssodh/init` moved connected False->True and left
    authenticated False. The first version of `verdict` had no branch for it and reported
    "No session — free to log in", which described the wrong state.
    """
    code, headline, guidance = verdict(GatewayState(reachable=True, connected=True, authenticated=False, user_id=1))
    assert code == EXIT_FREE
    assert "not authenticated" in headline.lower()
    assert "cannot supply an authentication" in guidance.lower()


def test_sso_alive_without_a_brokerage_session_is_free_and_prints_no_user_id():
    """The state this account was actually in — SSO valid, brokerage session absent. Until
    2026-10-12 the text named the IBKR user id ("IBKR knows you (userId …)") and this test
    required it; the operator reversed that on the day (gap #101): no reader acts on the
    number, and preflight output is pasted into records."""
    code, headline, guidance = verdict(GatewayState(reachable=True, user_id=99999999, connected=False))
    assert code == EXIT_FREE
    assert "sso alive" in headline.lower()
    assert "99999999" not in guidance


def test_an_unreachable_gateway_is_not_reported_as_a_free_session():
    """ "The gateway did not answer" and "no session exists" are opposite claims."""
    code, headline, _ = verdict(GatewayState(reachable=False, detail="ConnectionError"))
    assert code == EXIT_UNREACHABLE
    assert "not answering" in headline.lower()


def test_read_state_never_raises_on_a_dead_gateway():
    """This runs when things are already broken, so it has to survive that."""
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", side_effect=OSError("refused")):
        state = read_state("https://localhost:5055/v1/api")
    assert state.reachable is False
    assert "refused" in state.detail


def test_read_state_types_the_live_response_shape():
    """The wire spelling `collission` is corrected on our side, not propagated."""
    with patch(
        "ibkr_core_mcp.gateway.preflight.requests.get",
        return_value=_tickle(authenticated=True, connected=True, collission=True),
    ):
        state = read_state("https://localhost:5055/v1/api")
    assert state.authenticated and state.connected
    assert state.collision is True
    assert state.user_id == 99999999


def test_read_state_reads_both_endpoints_and_writes_to_neither():
    """Read-only is the whole contract: a check that can establish or destroy a session
    is not a check.

    Two GETs, deliberately — `/tickle` says whether *a* session is authenticated and
    `/sso/validate` says **whose** it is, and only the second explains a stuck login.
    Asserted over every call rather than the last one: with two GETs, checking
    `call_args` alone would silently stop covering `/tickle`.
    """
    with (
        patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=_tickle()) as get,
        patch("ibkr_core_mcp.gateway.preflight.requests.post") as post,
    ):
        read_state("https://localhost:5055/v1/api")
    urls = [c.args[0] for c in get.call_args_list]
    assert any(u.endswith("/tickle") for u in urls)
    assert any(u.endswith("/sso/validate") for u in urls)
    assert not post.called


# ── A borrowed SSO session ────────────────────────────────────────────────────


def _borrowed():
    """The state measured live on 2026-08-05: the phone's session, held by the gateway."""
    return GatewayState(
        reachable=True,
        authenticated=False,
        connected=False,
        competing=False,
        user_id=99999999,
        sso_valid=True,
        client_app="IBKRMOBILE_000.a-000",
        sso_user="ibkruser",
    )


def test_a_borrowed_session_names_the_app_holding_it():
    """The verdict must name the owning app — that is the whole diagnosis.

    Every weaker signal misled: userId was populated, ssoExpires was renewing, and
    competing was *false*, because the gateway never got far enough to register a claim.
    Only CLIENT_APP explains why the login is rejected however often it is retried.
    """
    code, headline, guidance = verdict(_borrowed())
    assert code == EXIT_BORROWED
    assert "IBKRMOBILE_000.a-000" in headline
    assert "log out" in guidance.lower()
    assert "swiping it away" in guidance.lower()  # closing != logging out


def test_a_borrowed_session_outranks_the_generic_not_authenticated_verdicts():
    """Ordering matters: 'free to log in' would send the user back into the retry loop."""
    code, _, _ = verdict(replace(_borrowed(), connected=True))
    assert code == EXIT_BORROWED


def test_release_is_never_reached_by_the_read_only_path():
    """`read_state` must not be able to release anything — its contract is read-only."""
    with (
        patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=_tickle()),
        patch("ibkr_core_mcp.gateway.preflight.requests.post") as post,
    ):
        read_state("https://localhost:5055/v1/api")
    assert not post.called


@pytest.mark.parametrize("body", [{}, {"CLIENT_APP": None}, {"CLIENT_APP": 12345}, "a bare string", [1, 2, 3], None])
def test_a_malformed_sso_body_degrades_instead_of_raising(body):
    """`read_state` promises never to raise, and an odd shape is what a sick gateway emits.

    A bare string or list is valid JSON, so `resp.json()` can return one; calling `.get`
    on it raised AttributeError straight out of `read_state` until 2026-08-05. Degrading
    means the borrowed-session verdict simply cannot fire — never that it fires wrongly.
    """
    tick = MagicMock()
    tick.status_code = 200
    tick.json.return_value = {"iserver": {"authStatus": {}}}
    sso = MagicMock()
    sso.status_code = 200
    sso.json.return_value = body

    with patch("ibkr_core_mcp.gateway.preflight.requests.get", side_effect=[tick, sso]):
        state = read_state("https://localhost:5055/v1/api")

    assert state.reachable is True
    assert isinstance(state.client_app, str)
    assert verdict(state)[0] in {
        EXIT_READY,
        EXIT_UNREACHABLE,
        EXIT_FREE,
        EXIT_CONTESTED,
        EXIT_BORROWED,
    }


def test_verdict_is_total_over_every_field_combination():
    """No state may fall through without a code, a headline and guidance.

    The verdict chain grew a branch at a time; an unreachable combination would surface as
    a blank message at exactly the moment someone needs to be told what to do.
    """
    import itertools

    for r, a, c, comp, coll, sso, app in itertools.product([True, False], repeat=7):
        state = GatewayState(
            reachable=r,
            authenticated=a,
            connected=c,
            competing=comp,
            collision=coll,
            sso_valid=sso,
            client_app="X" if app else "",
        )
        code, headline, guidance = verdict(state)
        assert code in {EXIT_READY, EXIT_UNREACHABLE, EXIT_FREE, EXIT_CONTESTED, EXIT_BORROWED}
        assert headline and guidance, f"empty verdict for {state}"


def test_a_401_means_alive_and_ready_not_down():
    """HTTP 401 is the gateway answering with "no session", not failing to answer.

    Measured 2026-08-05 straight after a container restart: both `/tickle` and
    `/sso/validate` returned 401 with empty bodies on a gateway that was running perfectly
    and waiting to be logged into. Folding that into `reachable=False` told the user
    "Gateway is NOT answering. Start it first" — wrong advice at the exact moment the
    session slot was finally clean.
    """
    resp = MagicMock()
    resp.status_code = 401
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=resp):
        state = read_state("https://localhost:5055/v1/api")

    assert state.reachable is True
    assert state.authenticated is False
    assert state.client_app == ""
    code, headline, _ = verdict(state)
    assert code == EXIT_FREE, "a clean gateway must read as free to log in"
    assert "not answering" not in headline.lower()


def test_a_genuine_transport_failure_is_still_down():
    """The 401 carve-out must not swallow a real outage."""
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", side_effect=OSError("refused")):
        assert verdict(read_state("https://localhost:5055/v1/api"))[0] == EXIT_UNREACHABLE

    resp = MagicMock()
    resp.status_code = 502
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=resp):
        assert verdict(read_state("https://localhost:5055/v1/api"))[0] == EXIT_UNREACHABLE


# ── Gap #93: the gateway's internal log — was the last login refused? ─────────────
#
# Synthetic lines in the shape `grep -HF` prints over the gateway's dated files: the path, a
# colon, then the line, which starts with its UTC time — the two parts measured on the real
# log (93 of 93 phrase lines); the rest of each line here is filler. No real line is copied: both repositories are
# public and the real log carries the username, cookies and device ids. Each phrase line
# below also carries an account-, token- and MAC-shaped string, so the exact-equality check
# proves that nothing but the time, the event and its code leaves the extractor.

_SECRETS = "U1234567 JSESSIONID=3f9c0a7be41d2c6a8f00ddee11223344 00:1a:2b:3c:4d:5e"
_LOG = "/app/api_gateway/logs/gw.{day}.log:{time}.123 filler [a-thread-0] {text} " + _SECRETS


def _grep(*lines: tuple[str, str, str]) -> str:
    """`grep -HF` output for (day, time, text) lines."""
    return "\n".join(_LOG.format(day=d, time=t, text=x) for d, t, x in lines) + "\n"


def test_a_log_line_becomes_its_time_event_and_code_and_nothing_else():
    """Each phrase line becomes (time, event, code) and nothing else: the account-, token- and
    MAC-shaped strings on every line must not survive into any field."""
    out = _grep(
        ("2026-10-07", "17:53:14", "Client login succeeds"),
        ("2026-10-07", "17:53:15", "-> GET /v1/api/sso/validate?gw=1,401"),
        ("2026-10-07", "17:53:15", "authentication to cp failed, retry 1"),
        ("2026-10-07", "17:53:27", "giving up"),
        ("2026-10-08", "16:15:18", "authenticated to cp"),
        ("2026-10-08", "16:15:23", "-> POST /v1/api/iserver/auth/ssodh/init,200"),
    )

    assert login_events(out) == [
        LoginEvent("2026-10-07 17:53:14", "login", ""),
        LoginEvent("2026-10-07 17:53:15", "validate", "401"),
        LoginEvent("2026-10-07 17:53:15", "retry", "1"),
        LoginEvent("2026-10-07 17:53:27", "giving up", ""),
        LoginEvent("2026-10-08 16:15:18", "authenticated", ""),
        LoginEvent("2026-10-08 16:15:23", "ssodh/init", "200"),
    ]


def test_events_come_out_in_time_order_whatever_order_the_files_were_read_in():
    """`grep -r` lists the dated files in directory order, not date order (measured 2026-10-12:
    the four files came back out of order), and `last_login` takes the LAST login in the list
    as the newest — so an older file read last would decide the verdict."""
    out = _grep(
        ("2026-10-09", "18:25:00", "Client login succeeds"),
        ("2026-10-07", "17:53:14", "Client login succeeds"),
    )
    assert [e.at for e in login_events(out)] == ["2026-10-07 17:53:14", "2026-10-09 18:25:00"]


def test_a_login_line_without_a_time_is_an_unknown_format_not_a_skipped_line():
    """Skipping it would make the rule answer about an OLDER login: a fresh refusal whose login
    line had lost its time would read as the previous login's "validated" — the #93 failure,
    silently. All 93 phrase lines measured start with their time, so such a line means the
    format changed: no verdict from partial data. The message names the event, never the line."""
    out = _grep(("2026-10-07", "17:53:14", "Client login succeeds"))
    out += "/app/api_gateway/logs/gw.2026-10-08.log:no time Client login succeeds " + _SECRETS + "\n"
    with pytest.raises(ValueError) as raised:
        login_events(out)
    assert str(raised.value) == "gateway log format not recognised: a 'login' line has no leading time"


_REFUSED = [
    ("login", ""),
    ("validate", "401"),
    ("retry", "1"),
    ("validate", "401"),
    ("retry", "2"),
    ("giving up", ""),
]
_REPEAT_REFUSED = [("login", ""), ("validate", "401"), ("retry", "6"), ("giving up", "")]
_VALIDATED = [("login", ""), ("validate", "200"), ("authenticated", ""), ("ssodh/init", "200")]
_IN_PROGRESS = [("login", ""), ("validate", "401"), ("retry", "1")]
# 2026-10-09 19:51 UTC: 86 minutes after a good login the gateway's validation lapsed by
# itself — retries and a "giving up" with no login line — and 20:37: a burst of 500s with
# "giving up" lines, recovered within a second. Neither is a refused login.
_LAPSE = [("validate", "401"), ("retry", "1"), ("giving up", "")]
_BURST = [
    ("validate", "500"),
    ("retry", "2"),
    ("giving up", ""),
    ("validate", "200"),
    ("authenticated", ""),
]


@pytest.mark.parametrize(
    ("shape", "outcome"),
    [
        (_REFUSED, "refused"),
        (_REPEAT_REFUSED, "refused"),
        (_VALIDATED, "validated"),
        (_IN_PROGRESS, "validating"),
        (_REFUSED + _VALIDATED, "validated"),
        (_VALIDATED + _REFUSED, "refused"),
        (_VALIDATED + _LAPSE, "validated"),
        (_VALIDATED + _BURST, "validated"),
    ],
    ids=[
        "refused",
        "refused-again-at-once",
        "validated",
        "still-validating",
        "a-good-login-after-a-refusal",
        "a-refusal-after-a-good-login",
        "a-lapse-without-a-login",
        "a-500-burst-without-a-login",
    ],
)
def test_the_last_login_decides(shape, outcome):
    """The rule, over every shape the archive holds (10-07 → 10-13): the newest login line,
    then `authenticated to cp` after it = validated, `giving up` after it = refused, neither
    = still validating. A `giving up` that belongs to no login of its own (a lapse, a burst of
    500s) never turns a validated login into a refusal."""
    events = [LoginEvent(f"2026-10-07 18:{i:02d}:00", e, c) for i, (e, c) in enumerate(shape)]
    newest = max(i for i, (e, _) in enumerate(shape) if e == "login")
    assert last_login(events) == LastLogin(events[newest].at, outcome)


def test_no_login_line_is_no_reading():
    """No login line — a re-created container, or only a lapse — is no reading at all, never a
    "validated" or a "refused" made up from the events around it."""
    assert last_login([LoginEvent("2026-10-09 19:51:22", "giving up", "")]) is None
    assert last_login([]) is None


# ── Gap #93, piece 3: a FREE reading, refined by the gateway's own log ───────────

_FREE = verdict(GatewayState(reachable=True))


def _events(shape: list[tuple[str, str]]) -> list[LoginEvent]:
    """Events one minute apart, in the order given."""
    return [LoginEvent(f"2026-10-07 18:{i:02d}:00", e, c) for i, (e, c) in enumerate(shape)]


@pytest.mark.parametrize(
    ("events", "problem", "code", "says"),
    [
        (_events(_REFUSED), "", EXIT_REFUSED, "IBKR's website"),
        (_events(_IN_PROGRESS), "", EXIT_VALIDATING, "Do not log in again"),
        (_events(_VALIDATED), "", EXIT_FREE, "(2026-10-07 18:00:00 UTC) was validated by IBKR"),
        ([], "", EXIT_FREE, "records no login"),
        (
            None,
            "Error response from daemon: No such container: x",
            EXIT_FREE,
            "No such container: x",
        ),
    ],
    ids=["refused", "validating", "validated", "no-login-recorded", "log-unreadable"],
)
def test_a_free_reading_is_refined_by_the_last_login(events, problem, code, says):
    """The five readings of the prototype the operator reviewed 2026-10-12: each gets its
    exit code and says the one fact it exists for — a log that cannot be read says so and
    keeps FREE, never a silent FREE that looks like a clean bill."""
    refined, _, guidance = refine_with_log(_FREE, events, problem)
    assert (refined, says in guidance) == (code, True)


def test_a_refused_login_is_told_the_website_login_first_and_is_never_forbidden_one():
    """The remedy that worked (2026-10-08 12:15 EDT) is a website login THEN one gateway login;
    a verdict that forbade the gateway login would deadlock it, since the log reads "refused"
    until that gateway login succeeds."""
    _, headline, guidance = refine_with_log(_FREE, _events(_REFUSED), "")
    assert "(2026-10-07 18:00:00 UTC)" in headline
    assert guidance.index("IBKR's website") < guidance.index("log in to the gateway once")


def test_the_log_never_overrides_a_reading_that_is_not_free():
    """A live session, or any other HTTP verdict, is the HTTP side's to state; an old refusal
    in the log must not turn it into REFUSED."""
    live = verdict(GatewayState(reachable=True, authenticated=True, connected=True))
    assert refine_with_log(live, _events(_REFUSED), "") == live


# ── confirm_session: the data half, and the portfolio prerequisite in one call ───────────────
#
# Moved from the owner module, where nothing tested it directly — the owner's own tests stand
# it in. Its contract: one GET of `/portfolio/accounts`, `(ok, detail)`, never raises for a
# gateway condition.

_URL = "https://localhost:5055/v1/api"


def _accounts(status: int, body: object) -> MagicMock:
    """A `/portfolio/accounts` response with the given status and JSON body."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    return resp


def test_confirm_session_is_one_get_of_portfolio_accounts_and_never_posts():
    """The one call discharges both obligations: it proves the data half answers and it is IBKR's
    documented prerequisite for the portfolio endpoints. A read, never a write."""
    with (
        patch(
            "ibkr_core_mcp.gateway.preflight.requests.get",
            return_value=_accounts(200, [{"accountId": "U1234567"}, {"accountId": "U7654321"}]),
        ) as get,
        patch("ibkr_core_mcp.gateway.preflight.requests.post") as post,
    ):
        ok, detail = confirm_session(_URL)
    assert ok is True
    assert detail == "account(s) U1234567, U7654321"
    assert [c.args[0] for c in get.call_args_list] == [f"{_URL}/portfolio/accounts"]
    assert not post.called


@pytest.mark.parametrize(
    ("status", "body", "says"),
    [
        (401, [], "HTTP 401"),
        (200, [], "no accounts"),
        (200, {"not": "a list"}, "no accounts"),
        (200, [{"no_id": 1}], "unnamed"),
    ],
    ids=["unauthorised", "empty-list", "not-a-list", "accounts-without-ids"],
)
def test_confirm_session_reports_a_half_established_session_as_not_ok(status, body, says):
    """A 200 with nothing in it is not a confirmation; an account row without an id is named as
    `unnamed`, still ok — the endpoint answered with a non-empty list."""
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=_accounts(status, body)):
        ok, detail = confirm_session(_URL)
    assert says in detail
    assert ok is (says == "unnamed")


def test_confirm_session_never_raises_and_redacts_the_failure():
    """It runs when things are already broken, so it survives that — and a `requests` error
    carries the request URL, so the detail passes `redact_error` (condition G): the type name
    survives, a query string does not."""
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='localhost', port=5055): Max retries exceeded with url: "
        "/v1/api/portfolio/accounts?session=SECRET-SESSION"
    )
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", side_effect=exc):
        ok, detail = confirm_session(_URL)
    assert ok is False
    assert "ConnectionError" in detail
    assert "SECRET-SESSION" not in detail


def test_confirm_session_reports_a_body_that_is_not_json():
    """The HTML page the gateway serves once its session lapses is a 200 that is not JSON."""
    resp = _accounts(200, None)
    resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
    with patch("ibkr_core_mcp.gateway.preflight.requests.get", return_value=resp):
        ok, detail = confirm_session(_URL)
    assert ok is False
    assert "not JSON" in detail


@pytest.mark.parametrize("reader", [read_state, confirm_session], ids=["read_state", "confirm_session"])
def test_a_non_loopback_url_is_refused_before_any_request(reader):
    """Condition C: the pin sits on a line before the certificate-exempt request. A non-loopback
    URL here is a programming error — the URL came from elsewhere — so it propagates as
    `ConfigError` rather than becoming an "unreachable" reading, and nothing is sent."""
    with (
        patch("ibkr_core_mcp.gateway.preflight.requests.get") as get,
        pytest.raises(ConfigError, match="localhost"),
    ):
        reader("https://gateway.example.com/v1/api")
    assert not get.called


# ── gateway_api_url: the one URL read, through the one loader ─────────────────────────────────
#
# Replaces the consumer's `gateway_url()`, which called `load_dotenv` (refused here by invariant
# 12's test, probe M5) and the keepalive script's own `.env` grammar in bash.


def test_gateway_api_url_defaults_to_the_local_gateway(monkeypatch):
    """`Config`'s own default, so the two cannot disagree."""
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    assert gateway_api_url() == "https://localhost:5055/v1/api"


def test_gateway_api_url_reads_the_env_file_given_and_strips_a_trailing_slash(tmp_path, monkeypatch):
    """A host whose `.env` lies elsewhere passes its path; the trailing slash goes, as the client's
    constructor strips it, so `f"{url}/tickle"` never carries two."""
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("IBKR_GATEWAY_URL=https://127.0.0.1:5056/v1/api/\n")
    env.chmod(0o600)
    assert gateway_api_url(env) == "https://127.0.0.1:5056/v1/api"


def test_gateway_api_url_refuses_a_non_loopback_gateway_before_any_request(tmp_path, monkeypatch):
    """The pin, applied where the URL is read: a command line prints this and exits before its
    first request."""
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("IBKR_GATEWAY_URL=https://gateway.example.invalid/v1/api\n")
    env.chmod(0o600)
    with pytest.raises(ConfigError, match="localhost"):
        gateway_api_url(env)


def test_gateway_api_url_reads_no_secret_into_the_environment(tmp_path, monkeypatch):
    """Invariant 12 carried into the gateway URL read: the file is read through `load_env_file`,
    so a secret beside the URL stays out of `os.environ` — the property the consumer's bash
    keepalive held with its own one-line grammar."""
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("IBKR_FLEX_TOKEN=not-a-real-token\nIBKR_GATEWAY_URL=https://localhost:5055/v1/api\n")
    env.chmod(0o600)
    assert gateway_api_url(env) == "https://localhost:5055/v1/api"
    assert "IBKR_FLEX_TOKEN" not in os.environ
