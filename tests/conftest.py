import os
import re
import sys
import types
from pathlib import Path

import pytest

# ── No unit test reaches the operator's data ────────────────────────────────────
#
# `Config.from_env()` defaults `sqlite_path` to `~/.ibkr_core/store.db` — an ABSOLUTE path, so
# no working directory and no `tmp_path` convention protects it — and `_no_real_secrets` below
# removes `IBKR_SQLITE_PATH` with every other `IBKR_` variable, so inside a unit test the
# default IS the operator's trade store: years of statements, parts of which cannot be pulled
# again. The same `Config` points the Drive token, the Drive credentials and the browser
# profiles under that directory. Until 2026-09-30 what kept the suite off it was every test
# remembering to pass `mock_config`. The Flex read API (`flex_dataset`, `flex_sync`) opens
# the store from a path, so the rule is made structural before those tests are written.
#
# An audit hook (https://docs.python.org/3.11/library/sys.html#sys.addaudithook), armed in
# `pytest_configure` before anything is collected, refuses any SQLite open of a database there
# and any file opened, created, changed or removed there, however the path names it — read-only
# opens included, since a `mode=ro` open of a WAL database can still create `-shm` and `-wal`
# beside it (https://www.sqlite.org/wal.html § 5, "Read-Only Databases"). SQLite's own event
# fires inside the connection, so every route is covered: `sqlite3.connect`, a reference taken
# earlier, `sqlite3.Connection`, `sqlite3.dbapi2`. The refusal is `pytest.fail`, a
# `BaseException`, raised before the operation happens. Integration tests are exempt from
# their setup to their teardown (`pytest_runtest_setup` / `_teardown` below): they run against
# the operator's live gateway and configured store, which is their subject.
#
# It replaced (claudia_ui's Flex boundary plan, § 13 item 15) a `sqlite3.connect` swapped by an
# autouse fixture, whose holes a review of claudia_ui's copy measured: not armed at import or
# in a module-scoped fixture; `Connection()` and `sqlite3.dbapi2.connect` went around it; it
# read URIs with `urllib`, so a `%00` tail or a raw newline reached the store; another letter
# case (APFS ignores case) and the `/System/Volumes/Data` firmlink passed its comparison by
# name; nothing covered files; and `SQLiteStore` changed the directory's mode before the
# refusal. `tests/security/test_no_real_data_io.py` is what fails when this stops working.
#
# What it cannot see, stated rather than implied: SQL-level `ATTACH` and `VACUUM INTO` (SQLite
# opens those files itself, with no Python event), a path relative to a `dir_fd`, and anything
# that disables it on purpose — audit hooks are "not suitable for implementing a sandbox"
# (Python's own documentation). It is there to catch accidents.
_OPERATOR_DATA_DIR = (Path.home() / ".ibkr_core").resolve()
_REAL_OPERATOR_DATA_DIR = _OPERATOR_DATA_DIR
_OPERATOR_GUARD = {"armed": False}  # a hook cannot be removed, only disarmed
_operator_refusals: list[str] = []  # of the real directory; read by `pytest_sessionfinish`

# Each audited file event, with the positions of its arguments that name a place opened,
# created, changed or removed. Argument order: https://docs.python.org/3.11/library/audit_events.html
# (checked 2026-09-30). `open` is `open()`, `io.open`, `os.open` and `io.open_code` alike. A
# symlink's own target is not a touch — opening through it is, and is judged where it lands.
_FILE_EVENTS: dict[str, tuple[int, ...]] = {
    "open": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.link": (0, 1),
    "os.mkdir": (0,),
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.rmdir": (0,),
    "os.symlink": (1,),
    "os.truncate": (0,),
    "os.utime": (0,),
    "shutil.copyfile": (0, 1),
    "shutil.copytree": (0, 1),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "tempfile.mkdtemp": (0,),
    "tempfile.mkstemp": (0,),
}
_HEX_OCTET = re.compile(rb"[0-9A-Fa-f]{2}")


def _sqlite_uri_path(uri: str) -> str | None:
    """The file SQLite opens for a `file:` URI — its own parse, not `urllib`'s — or None.

    `sqlite3ParseUri` in SQLite's `src/main.c`, as built here (no `SQLITE_ALLOW_URI_AUTHORITY`):
    an authority after `//` runs to the next `/` and must be empty or `localhost` — anything
    else is an error and nothing opens (None); the path ends at the first `?` or `#`; `%HH` is
    decoded; and at a `%00` the rest of the path is ignored. `urllib` differs exactly there: it
    decodes `%00` into the path, deletes raw tabs and newlines, and raises on a `[` in the
    authority — three ways the store was reached, or the guard itself raised, before this.
    """
    rest = uri[len("file:") :]
    if rest.startswith("//"):
        authority, slash, path = rest[2:].partition("/")
        if authority not in ("", "localhost"):
            return None
        rest = slash + path
    for end in ("?", "#"):
        rest = rest.partition(end)[0]
    raw = rest.encode("utf-8", "surrogateescape")
    decoded = bytearray()
    at = 0
    while at < len(raw):
        escape = raw[at + 1 : at + 3]
        if raw[at] == ord("%") and _HEX_OCTET.fullmatch(escape):
            if escape == b"00":
                break
            decoded.append(int(escape, 16))
            at += 3
        else:
            decoded.append(raw[at])
            at += 1
    return os.fsdecode(bytes(decoded))


def _inside_operator_directory(path: Path) -> bool:
    """True when `path` is the operator's directory or lies under it — by name, or by identity.

    By name after `resolve()`, which follows symlinks. By identity for the spellings
    `resolve()` leaves apart — another letter case on a case-insensitive volume, a firmlink
    such as `/System/Volumes/Data/Users/...`: `os.path.samestat` of the directory against
    `path` and each of its existing ancestors. Where the directory does not exist (CI) there
    is nothing to reach, and the comparison by name alone stands.
    """
    if path.is_relative_to(_OPERATOR_DATA_DIR):
        return True
    try:
        operator = _OPERATOR_DATA_DIR.stat()
    except OSError:
        return False
    for place in (path, *path.parents):
        try:
            if os.path.samestat(place.stat(), operator):
                return True
        except OSError:
            continue
    return False


def _operator_path(value: object, *, database: bool) -> Path | None:
    """The place under the operator's data directory that `value` names, or None.

    `value` is what the audited call was given: `str`, `bytes` or a path object — and, for a
    database, the `file:` URI form, read the way SQLite reads it. `~` is expanded, which SQLite
    would not do: a test that spells the store that way meant the operator's, and is refused
    as if it had reached it. Anything that names no place there — `:memory:`, an empty name, a
    file descriptor, a path elsewhere — is None, and so is a name no file system can hold (a
    NUL): the call refuses that one itself, in its own words.
    """
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not isinstance(value, str | os.PathLike):
        return None
    text = os.fspath(value)
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if database and text.startswith("file:"):
        uri_path = _sqlite_uri_path(text)
        if uri_path is None:
            return None
        text = uri_path
    if not text or (database and text == ":memory:"):
        return None
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):  # a NUL, an unencodable name, an unknown ~user
        return None
    return resolved if _inside_operator_directory(resolved) else None


def _operator_data_hook(event: str, args: tuple[object, ...]) -> None:
    """The audit hook: refuse a SQLite open or a file operation under the operator's directory."""
    if not _OPERATOR_GUARD["armed"]:
        return
    if event == "sqlite3.connect":
        targets = [_operator_path(args[0], database=True)]
    elif (positions := _FILE_EVENTS.get(event)) is not None:
        targets = [_operator_path(args[p], database=False) for p in positions if p < len(args)]
    else:
        return
    for target in targets:
        if target is None:
            continue
        if _OPERATOR_DATA_DIR == _REAL_OPERATOR_DATA_DIR:
            _operator_refusals.append(f"{event} {target}")
        pytest.fail(
            f"a unit test tried to reach the operator's data ({event}: {target.name} under "
            "~/.ibkr_core) — build it under tmp_path (the `mock_config` fixture does)",
            pytrace=True,
        )


def _refusal_violations(refusals: list[str]) -> list[str]:
    """One violation per recorded refusal of the real directory — the decision behind
    `pytest_sessionfinish`, as a pure function."""
    return [f"a test reached for the operator's data directory: {refusal}" for refusal in refusals]


# ── No unit test reaches a human ────────────────────────────────────────────────
#
# The two order gates end at a person: Gate 1 is Apple's LocalAuthentication prompt
# (`human_auth.require_touch_id`), Gate 2 a dialog (`order_confirm`). Until 2026-10-01 what
# kept a unit test from opening either was every test remembering to replace both. On that
# day a mutation run skipped Gate 1 in `cancel_order`; the test had replaced Touch ID alone,
# so the code walked on to the REAL Gate 2 dialog, on the operator's screen, during a live
# session. Nothing reached IBKR — the DELETE was a mock and sockets are blocked — but whether
# the mutant was "caught" was decided by which button a person pressed, and five older tests
# had the same shape (register F32). So the rule is structural, like the two above it.
#
# A gate reaches a person through four doors, each shut in `pytest_configure`:
#
# 1. `LocalAuthentication` — Gate 1 runs in-process through PyObjC, with no audit event, so
#    the framework itself is replaced in `sys.modules`. `require_touch_id` imports it inside
#    the call, so the stand-in is what it gets.
# 2. `AppKit` — the same, for `_order_dialog` run inside the test process.
# 3. `tkinter.Tk` — the non-macOS dialog; replaced where tkinter can be imported at all.
# 4. A child process running `_order_dialog.py` or `osascript` — how `order_confirm` shows the
#    dialog on macOS. Python audits process creation, so the audit hook refuses those two by
#    the name of what would run, whichever function asked.
#
# The refusal is `pytest.fail`, a `BaseException`: it passes `require_touch_id`'s
# `except ImportError` and `_show_confirm_dialog`'s `except Exception` fallback alike. Nothing
# is exempt, integration tests included — none of them drives a gate. A test OF a gate places
# its own double for its own duration (`monkeypatch.setitem(sys.modules, …)`,
# `patch("…order_confirm.subprocess.run")`), as those tests always did.
# `tests/security/test_no_human_reached.py` is what fails when a door is open, and every test
# there is safe on a broken guard.
#
# What it cannot see, stated rather than implied: a prompt raised by code that already holds a
# reference to the real framework taken before configure time, a dialog shown by a child of a
# child under another name, and anything that disables it on purpose. It catches accidents.
_HUMAN_GUARD = {"armed": False}
_human_refusals: list[str] = []  # read by `pytest_sessionfinish`
_DIALOG_LAUNCHERS = ("_order_dialog.py", "osascript")
# Process creation, with the positions of the arguments that say what would run. Argument
# order: https://docs.python.org/3.11/library/audit_events.html (checked 2026-10-01).
_PROCESS_EVENTS: dict[str, tuple[int, ...]] = {
    "subprocess.Popen": (0, 1),  # executable, args
    "os.system": (0,),  # command
    "os.posix_spawn": (0, 1),  # path, argv
    "os.exec": (0, 1),  # path, args
    "os.spawn": (1, 2),  # mode, path, args
}


def _refuse_human(door: str) -> None:
    """Record the attempt and fail the test: a unit test was about to reach a person."""
    _human_refusals.append(door)
    pytest.fail(
        f"a unit test tried to reach a human ({door}) — replace the gate in the test: Touch ID "
        "with a LocalAuthentication double, the dialog with a patch of the confirm function or "
        "of order_confirm.subprocess.run",
        pytrace=True,
    )


class _NoHumanFramework(types.ModuleType):
    """A stand-in for a GUI framework: importing it works, using it is refused.

    Dunder lookups answer `AttributeError` like any module without the attribute — pytest,
    coverage and `inspect` read those off everything in `sys.modules`, and that is not a test
    reaching a person.
    """

    def __getattr__(self, name: str) -> object:
        """Refuse any real use; stay an ordinary module for introspection."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if _HUMAN_GUARD["armed"]:
            _refuse_human(f"{self.__name__}.{name}")
        raise AttributeError(name)


_GATE_1_FRAMEWORK = _NoHumanFramework("LocalAuthentication")
_DIALOG_FRAMEWORK = _NoHumanFramework("AppKit")
_displaced: dict[str, object] = {}  # what configure replaced, put back by unconfigure


def _no_tk_window(*args: object, **kwargs: object) -> None:
    """What `tkinter.Tk` is during the run."""
    _refuse_human("tkinter.Tk")


def _names_a_dialog_launcher(value: object) -> str | None:
    """The dialog launcher `value` would run, if any: a path, a command line, or a list of them."""
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, str):
        # One string is a path (`executable`) or a whole shell command (`os.system`): look at
        # each word's last component, so `…/tests/_order_dialog_helper.py` is not a launcher.
        for word in value.split():
            name = word.strip("'\"").rsplit("/", 1)[-1]
            if name in _DIALOG_LAUNCHERS:
                return name
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            if (found := _names_a_dialog_launcher(item)) is not None:
                return found
    return None


def _human_hook(event: str, args: tuple[object, ...]) -> None:
    """The audit hook: refuse a child process that would show a Gate 2 dialog."""
    if not _HUMAN_GUARD["armed"]:
        return
    positions = _PROCESS_EVENTS.get(event)
    if positions is None:
        return
    for position in positions:
        if position < len(args) and (launcher := _names_a_dialog_launcher(args[position])) is not None:
            _refuse_human(f"{event} {launcher}")


def _shut_the_tk_door(tkinter_module: types.ModuleType) -> None:
    """Replace `Tk` on a tkinter module, keeping the original for `_open_the_doors_again`.

    Its own function so the replacement is tested on a machine without tkinter too — a Python
    built without Tcl/Tk has no door to shut, and the branch below would never run there.
    """
    _displaced["tkinter.Tk"] = tkinter_module.Tk
    tkinter_module.Tk = _no_tk_window  # type: ignore[attr-defined]


def _shut_the_doors_to_a_human() -> None:
    """Replace the two frameworks and `tkinter.Tk`, and arm the process hook. Called once,
    from `pytest_configure`."""
    for stand_in in (_GATE_1_FRAMEWORK, _DIALOG_FRAMEWORK):
        _displaced[stand_in.__name__] = sys.modules.get(stand_in.__name__, _displaced)
        sys.modules[stand_in.__name__] = stand_in
    try:
        import tkinter
    except ImportError:  # no tkinter, no door: `order_confirm.tk` is None there too
        pass
    else:
        _shut_the_tk_door(tkinter)
    sys.addaudithook(_human_hook)
    _HUMAN_GUARD["armed"] = True


def _open_the_doors_again() -> None:
    """Undo `_shut_the_doors_to_a_human` (an audit hook cannot be removed, only disarmed)."""
    _HUMAN_GUARD["armed"] = False
    for name in (_GATE_1_FRAMEWORK.__name__, _DIALOG_FRAMEWORK.__name__):
        was = _displaced.pop(name, _displaced)
        if was is _displaced:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = was  # type: ignore[assignment]
    if "tkinter.Tk" in _displaced:
        import tkinter

        tkinter.Tk = _displaced.pop("tkinter.Tk")  # type: ignore[assignment,misc]


def _human_violations(refusals: list[str]) -> list[str]:
    """One violation per recorded attempt — the decision behind `pytest_sessionfinish`, as a
    pure function."""
    return [f"a test tried to reach a human: {refusal}" for refusal in refusals]


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test_store.db"


@pytest.fixture
def mock_config(tmp_path, tmp_db):
    """Config with safe defaults for unit tests."""
    from ibkr_core_mcp.config import Config

    return Config(
        gateway_url="https://localhost:5055/v1/api",
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp_db,
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
    )


# These tests' entire purpose is exercising the real SSRF/DNS validation path
# (ClaudeToolkit._validate_public_url -> local_browser.is_private_host ->
# socket.gethostbyname) against a real public hostname (example.com/wsj.com).
# Discovered while adding _no_real_io below: unrelated to the 3 sleep/network
# bugs that fixture was built to catch (see
# docs/plans/archive/testing-audits/2026-07-08-claude-tools-test-reorg-design.md), and pre-dates this
# reorg. Mocking DNS resolution here would weaken coverage of security-critical
# SSRF logic (see SECURITY.md § SSRF Prevention (Web Scraping)), so these are
# exempted by name instead of having DNS mocked away.
#
# THIS SET IS A SECURITY EXEMPTION LIST. An entry grants a test the right to make
# real DNS calls, so a name that no longer matches any test is not harmless — it is
# an exemption nothing uses, and it makes the set look better-audited than it is.
# Three such names survived here from tools deleted on 2026-07-30 and were removed
# on 2026-08-07; prune in the same commit as any test deletion.
#
# Every entry is here for one reason: the handler SSRF-validates before doing its
# real work, so blocked DNS short-circuits the tool into "Blocked: ..." / "Invalid
# URL: ..." and the test's assertions stop meaning anything — they would pass for
# the wrong reason. The matching "...blocks_a_private_..." tests are deliberately
# NOT listed: they want the rejection, and localhost/127.0.0.1 need no DNS to be
# recognised.
_REAL_DNS_EXEMPT_TESTS = {
    "test_validate_public_url_allows_public_https",
    # fetch_page handler tests — _handle_fetch_page validates the URL before
    # constructing the browser.
    "test_fetch_page_returns_the_pages_markdown",
    "test_fetch_page_names_the_saved_login_profile_when_one_applies",
    "test_fetch_page_says_how_to_create_a_profile_when_none_applies",
    "test_fetch_page_reports_crawl4ai_unavailable_without_raising",
    "test_fetch_page_reports_an_empty_fetch_instead_of_claiming_success",
    "test_fetch_page_reports_a_browser_failure_instead_of_raising",
    "test_fetch_page_flags_a_thin_result_instead_of_presenting_it_as_the_page",
    "test_fetch_page_does_not_cry_wolf_on_a_full_page",
    # search_site handler tests — _handle_search_site validates the domain before the
    # seeder runs.
    "test_search_site_ranks_and_points_at_fetch_page",
    "test_search_site_says_nothing_matched_rather_than_returning_an_empty_list",
    "test_search_site_does_not_claim_pages_were_read_when_none_were_discovered",
    "test_search_site_does_not_claim_pages_were_scored_when_none_were",
    "test_search_site_reports_a_missing_package_without_raising",
    "test_search_site_needs_no_firecrawl_key",
    # crawl_site handler tests — the root URL is validated before the browser runs.
    "test_crawl_site_refuses_to_archive_an_error_page_as_content",
    "test_crawl_site_still_archives_a_genuinely_short_page",
    "test_crawl_site_needs_no_firecrawl_key",
    "test_crawl_site_uses_the_48h_drive_cache",
}


def pytest_configure(config):
    """Block sockets from the moment the session starts, so module import and collection
    are covered too. From the first test on, pytest-socket's own per-test hooks take over
    (see `pytest_collection_modifyitems`); its teardown re-enables sockets after every
    test, which is why this call alone is not the per-test guarantee."""
    from pytest_socket import disable_socket

    disable_socket(allow_unix_socket=True)
    # The operator-data hook is armed here for the same reason: from here on, test modules are
    # imported and fixtures of every scope run, and a function-scoped fixture would arm it only
    # for the test body.
    sys.addaudithook(_operator_data_hook)
    _OPERATOR_GUARD["armed"] = True
    # And the two gates, for the same reason again: a module-scoped fixture or an import can
    # reach Touch ID or a dialog as easily as a test body can.
    _shut_the_doors_to_a_human()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run if a refusal of the operator's directory, or of a human gate, was swallowed.

    A refusal raised in a thread fails no test, and `except BaseException` would hide one
    anywhere, so every refusal of the real directory is recorded and reported here. A hook
    rather than a test because no test can run last by construction; `session.exitstatus` is
    what `pytest.main` returns after this hook, so setting it is what turns the run red.
    """
    violations = _refusal_violations(_operator_refusals)
    reached = _human_violations(_human_refusals)
    if not violations and not reached:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    lines: list[str] = []
    if violations:
        lines += ["", "REAL DATA REACHED FOR BY THE TEST SUITE (tests/conftest.py, constitution §7):", *violations]
    if reached:
        lines += ["", "A HUMAN GATE REACHED FOR BY THE TEST SUITE (tests/conftest.py, register F32):", *reached]
    for line in lines:
        if reporter is not None:
            reporter.write_line(line, red=True, bold=True)
        else:  # pragma: no cover - no terminal plugin
            print(line)
    session.exitstatus = 1


def pytest_unconfigure(config):
    from pytest_socket import enable_socket

    _OPERATOR_GUARD["armed"] = False
    _open_the_doors_again()
    enable_socket()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Disarm the operator-data hook for an integration test, before its fixtures are filled —
    `tryfirst`, so a module-scoped `live_client` is set up inside the exemption."""
    if item.get_closest_marker("integration"):
        _OPERATOR_GUARD["armed"] = False


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    """Arm it again after an integration test's fixtures are torn down — `trylast`, for the
    same module-scoped reason."""
    if item.get_closest_marker("integration"):
        _OPERATOR_GUARD["armed"] = True


def pytest_collection_modifyitems(config, items):
    """Give every test pytest-socket's own marker, so the block is applied by the plugin's
    `pytest_runtest_setup` — which runs BEFORE any fixture, module-scoped ones included.

    Review 2026-09-13: a session-wide `disable_socket()` plus a function-scoped fixture that
    re-enabled sockets for integration tests left the first live module's module-scoped
    `live_client` fixture blocked; `ping()` swallowed the `SocketBlockedError` and the whole
    module skipped as "gateway not reachable" with a green summary. The plugin's marker path
    enables or disables at the right moment for every scope. Integration tests and the
    DNS-exempt tests get `enable_socket`; everything else gets `disable_socket`
    (`--allow-unix-socket` in `addopts` keeps asyncio's self-pipe working).
    """
    for item in items:
        if item.get_closest_marker("integration") or item.name in _REAL_DNS_EXEMPT_TESTS:
            item.add_marker(pytest.mark.enable_socket)
        else:
            item.add_marker(pytest.mark.disable_socket)


@pytest.fixture(autouse=True)
def _no_real_io(request, monkeypatch):
    """Block real sleeps in every non-integration test.

    Added after discovering 3 claude_tools tests and 6 client.py tests were silently paying
    real wall-clock time (unmocked time.sleep) or making a real network call (unmocked
    Crawl4AI construction) despite being "unit" tests. The network half now lives in
    `pytest_collection_modifyitems` above (pytest-socket markers); this fixture keeps only
    the sleep stub, and exempts the same tests.
    """
    if request.node.get_closest_marker("integration") or request.node.name in _REAL_DNS_EXEMPT_TESTS:
        yield
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    yield


@pytest.fixture
def client(mock_config):
    """An `IBKRClient` with no auth and the accounts pre-initialised — shared by
    `tests/test_client.py` and `tests/security/` (was copied in three places)."""
    from ibkr_core_mcp.auth import NoAuth
    from ibkr_core_mcp.client import IBKRClient

    c = IBKRClient(mock_config, auth=NoAuth())
    # Pre-mark accounts as initialized so order/auth tests don't need to also mock the
    # /iserver/accounts prerequisite call. Tests for _ensure_accounts_initialized() itself
    # reset this flag explicitly.
    c._accounts_initialized = True
    return c


# Every variable this package reads carries one of these prefixes (`Config.from_env`,
# `IBKR_AUTH_BROWSER` in claude_tools, `CRAWL4AI_PROFILES_DIR`). Scrubbing by prefix, not by
# a hand-kept list: the first version listed 14 names, the test that checked them listed 7,
# and neither had `IBKR_AUTH_BROWSER` (review 2026-09-13).
#
# `ANTHROPIC_` is deliberately kept although **nothing in this package reads it any more**
# (TOOL-07, 2026-09-17, removed `Config.anthropic_api_key`). The scrubber's job is to keep
# the operator's real secrets out of unit tests, not to mirror what the package consumes:
# `ANTHROPIC_API_KEY` is still in the `.env` that `load_dotenv` can pull into `os.environ`,
# and is the most valuable key there. Removing this prefix as "unused" would be a security
# regression, so the reason is written here rather than left to be inferred.
_SECRET_ENV_PREFIXES = ("IBKR_", "GDRIVE_", "GOOGLE_", "FIRECRAWL_", "ANTHROPIC_", "CRAWL4AI_")


@pytest.fixture(autouse=True)
def _no_real_secrets(request, monkeypatch):
    """Keep the operator's `.env` and environment out of every non-integration test.

    Constructing `Config(...)` runs `load_dotenv()` through the `crawl4ai_profiles_dir`
    default factory, which walks up from `config.py` and loads the repository's real
    `.env` into `os.environ` — probed 2026-09-13: FIRECRAWL_API_KEY and GDRIVE_* appeared
    in a unit test's environment (docs/audits/security-architecture-audit-2026-09-13.md,
    B6). pytest-socket stops that key from reaching the network, but a test asserting on
    `os.environ` or calling `Config.from_env()` would silently use real values and pass
    for the wrong reason. `load_dotenv` becomes a no-op at every import site and every
    variable with a package prefix is removed; tests/security/test_no_live_io.py holds this.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return
    noop = lambda *args, **kwargs: False  # noqa: E731
    monkeypatch.setattr("ibkr_core_mcp.config.load_dotenv", noop)
    monkeypatch.setattr("dotenv.load_dotenv", noop)
    monkeypatch.setattr("dotenv.main.load_dotenv", noop)
    for name in [k for k in os.environ if k.startswith(_SECRET_ENV_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def _pacer_on_a_fake_clock(request, monkeypatch):
    """Unit tests exercise the real pacing logic without spending real seconds.

    `EndpointPacer` is process-wide, which is right in production and wrong in a test
    session: `/iserver/account/orders` is 1 req/5 secs, so the eight `get_live_orders`
    tests queued behind one another and added ~35 s to the suite. Swapping the clock,
    rather than disabling the pacer, keeps every decision it makes observable — the
    waits still happen, they just cost nothing.

    INTEGRATION TESTS ARE DELIBERATELY EXCLUDED. They talk to the real gateway, where
    pacing is the thing standing between a live run and a fifteen-minute penalty box on
    this machine's IP, and a fake clock there would remove the protection precisely
    where it matters. A test that wants to assert on pacing builds its own pacer.
    """
    if request.node.get_closest_marker("integration"):
        return

    from ibkr_core_mcp import rate_limiter

    now = [0.0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(
        rate_limiter,
        "_pacer",
        rate_limiter.EndpointPacer(clock=clock, sleep=sleep),
    )
