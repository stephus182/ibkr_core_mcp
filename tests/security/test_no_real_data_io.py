"""Security constitution §7, second half — a unit test cannot reach the operator's data.

The trade store's default path is absolute (`~/.ibkr_core/store.db`) and the unit-test scrub
removes `IBKR_SQLITE_PATH`, so a test that builds `Config.from_env()` and opens the store would
be opening the operator's real trade history; the same `Config` points the Drive token, the
Drive credentials and the browser profiles under that directory too. Since the Flex read API
(`flex_dataset`, `flex_sync`) opens the store from a path argument, the rule is structural:
an audit hook in `tests/conftest.py`, armed before anything is collected, refuses any SQLite
open of a database there and any file opened, created, changed or removed there, however the
path names it, and the run fails at session end if a refusal was swallowed. Integration tests
alone are exempt, from their setup to their teardown. This file is what fails when any of
that stops being true.

It replaced (claudia_ui plan § 13, item 15) a `sqlite3.connect` swapped by a function-scoped
fixture, whose holes a review of claudia_ui's copy measured: not armed at import or in a
module-scoped fixture; `sqlite3.Connection()` and `sqlite3.dbapi2.connect` went around it; a
`urllib` parse let a `%00` tail or a raw newline through; another letter case and the
`/System/Volumes/Data` firmlink passed a comparison by name; nothing covered files; and
`SQLiteStore` changed the directory's mode before the refusal.

Every test below first points the guard at a stand-in under `tmp_path` — a store and a token
in it, built BEFORE it is guarded — so a broken guard, which is how each test was proven able
to fail, touches a scratch file, never the operator's.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sqlite3
import tempfile
import threading
import traceback
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests import conftest

pytestmark = pytest.mark.security

CAPTURED_CONNECT = sqlite3.connect  # a reference taken at import, before any fixture ran


def _refused_now() -> bool:
    """Whether the guard refuses, at this moment, an open in a scratch stand-in directory —
    behaviour, not a flag: a guard armed only around test bodies would still show one."""
    stand_in = Path(tempfile.mkdtemp(prefix="guard-probe-")).resolve()
    guarded = conftest._OPERATOR_DATA_DIR
    conftest._OPERATOR_DATA_DIR = stand_in
    try:
        sqlite3.connect(stand_in / "probe.db").close()
    except pytest.fail.Exception:
        return True
    finally:
        conftest._OPERATOR_DATA_DIR = guarded
        shutil.rmtree(stand_in, ignore_errors=True)
    return False


REFUSED_AT_IMPORT = _refused_now()


@pytest.fixture
def operator_dir(tmp_path, monkeypatch):
    """A stand-in for `~/.ibkr_core`, holding a store and a token, installed as the directory
    the guard protects. Built first: from then on the guard refuses the test itself."""
    fake = (tmp_path / ".ibkr_core").resolve()
    fake.mkdir(mode=0o755)
    store = sqlite3.connect(fake / "store.db")
    store.execute("CREATE TABLE marker (v)")
    store.execute("INSERT INTO marker VALUES ('the operator')")
    store.commit()
    store.close()
    (fake / "token.json").write_text('{"token": "stand-in"}')
    monkeypatch.setattr(conftest, "_OPERATOR_DATA_DIR", fake)
    return fake


def _state(directory: Path) -> tuple[object, ...]:
    """What a touch could change: the directory's mode, and each entry's name, size, mode and
    mtime — read with `stat` and a listing, which the guard does not watch."""
    entries = sorted((p.name, p.stat().st_size, p.stat().st_mode, p.stat().st_mtime_ns) for p in directory.iterdir())
    return directory.stat().st_mode, tuple(entries)


def _item(*markers: str) -> MagicMock:
    """A stand-in for a collected test item carrying `markers`, as the runtest hooks see it."""
    item = MagicMock()
    item.get_closest_marker = lambda name: pytest.mark.integration if name in markers else None
    return item


@pytest.fixture(scope="module")
def refused_in_a_module_fixture():
    """Whether the guard refused an open while a module-scoped fixture ran."""
    return _refused_now()


def test_the_guard_refuses_before_any_test_body_runs(refused_in_a_module_fixture):
    """It refuses at import and in a fixture of wider scope, not only in the test body — the
    swapped `sqlite3.connect` it replaced did neither (measured on claudia_ui's copy)."""
    assert REFUSED_AT_IMPORT is True
    assert refused_in_a_module_fixture is True


def test_the_guarded_directory_is_where_the_default_store_lives():
    """After the scrub, `Config.from_env()` falls back to the operator's store — an absolute
    path, so no working directory protects it — and the guard recognises it. The directory is
    named resolved, so one that is itself a link is guarded where it lands."""
    from ibkr_core_mcp.config import Config

    assert (Path.home() / ".ibkr_core").resolve() == conftest._OPERATOR_DATA_DIR
    default = Config.from_env().sqlite_path
    assert default == Path("~/.ibkr_core/store.db").expanduser()
    assert conftest._operator_path(default, database=True) is not None


def test_the_drive_token_and_credentials_default_there_too():
    """The scrub removes every `GDRIVE_*` and `CRAWL4AI_*` variable, so a real `Config` in a
    test points its Drive token, its Drive credentials and its browser profiles at their
    defaults — all under the guarded directory, which the old guard never watched."""
    from ibkr_core_mcp.config import Config

    config = Config.from_env()
    for path in (
        config.gdrive_token_file,
        config.gdrive_credentials_file,
        config.crawl4ai_profiles_dir,
    ):
        assert conftest._operator_path(path, database=False) is not None, path


SPELLINGS = {
    "str": lambda d: str(d / "store.db"),
    "path": lambda d: d / "store.db",
    "bytes": lambda d: str(d / "store.db").encode(),
    "file-uri": lambda d: f"file:{d / 'store.db'}?mode=ro",
    "as-uri": lambda d: f"{(d / 'store.db').as_uri()}?mode=ro",
    "uri-with-fragment": lambda d: f"{(d / 'store.db').as_uri()}?mode=rw#fragment",
    "localhost-authority": lambda d: f"file://localhost{d / 'store.db'}?mode=ro",
    "percent-escaped": lambda d: f"file:{d.parent}/%2Eibkr%5Fcore/store.db?mode=ro",
    "percent-00-tail": lambda d: f"{(d / 'store.db').as_uri()}%00tail?mode=ro",
    "raw-newline": lambda d: f"file:{d}/.\n./../store.db?mode=ro",
    "wal-sidecar": lambda d: str(d / "store.db") + "-wal",
    "nested": lambda d: str(d / "nested" / "other.db"),
    "dot-dot": lambda d: str(d / "sub" / ".." / "store.db"),
}


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_every_spelling_of_a_database_there_is_refused_before_it_opens(operator_dir, spelling):
    """Each form SQLite accepts for a file in the directory — a URI read the way SQLite reads
    it — is refused, and nothing there changes. `percent-00-tail` and `raw-newline` reached the
    store through a `urllib` parse (measured on claudia_ui's copy, 2026-09-30)."""
    before = _state(operator_dir)
    database = SPELLINGS[spelling](operator_dir)
    is_uri = isinstance(database, str) and database.startswith("file:")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(database, uri=is_uri)
    assert _state(operator_dir) == before


def test_another_letter_case_of_the_directory_is_refused(operator_dir):
    """APFS, macOS's default, ignores case: `.IBKR_CORE` is the same directory, and a
    comparison by name let it through (measured 2026-09-30)."""
    alias = operator_dir.parent / operator_dir.name.upper()
    if not alias.exists():
        pytest.skip("a case-sensitive file system: another case names another directory")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(alias / "store.db")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        os.chmod(alias, 0o700)  # the directory itself, not only what lies under it


def test_the_data_volume_firmlink_is_refused(operator_dir):
    """On macOS `/System/Volumes/Data` reaches the same inode as `/Users` and `/private`, and
    `resolve()` does not follow a firmlink (measured 2026-09-30)."""
    alias = Path("/System/Volumes/Data" + str(operator_dir))
    if not (alias.exists() and os.path.samefile(alias, operator_dir)):
        pytest.skip("no /System/Volumes/Data firmlink here: it is macOS's")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(alias / "store.db")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        os.chmod(alias, 0o700)  # the directory itself, not only what lies under it


def test_the_directory_is_guarded_before_it_exists(tmp_path, monkeypatch):
    """Where there is no such directory — CI, a fresh machine — identity has nothing to compare
    and the name alone guards it: a test must not be what creates the directory or its store."""
    absent = (tmp_path / ".ibkr_core").resolve()
    monkeypatch.setattr(conftest, "_OPERATOR_DATA_DIR", absent)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        absent.mkdir()
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(absent / "store.db")
    assert not absent.exists()


def test_a_path_through_a_symlink_is_judged_where_it_lands(operator_dir, tmp_path):
    """The operator's directory may be reached through a link."""
    link = tmp_path / "link-to-the-directory"
    link.symlink_to(operator_dir, target_is_directory=True)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(link / "store.db")


def test_the_directory_named_through_a_link_is_still_recognised(operator_dir, tmp_path, monkeypatch):
    """Were the directory itself a link, named unresolved, its identity would still hold it —
    the constant is resolved as well, so this is the second line, not the only one."""
    link = tmp_path / "linked-data-dir"
    link.symlink_to(operator_dir, target_is_directory=True)
    monkeypatch.setattr(conftest, "_OPERATOR_DATA_DIR", link)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(operator_dir / "store.db")


def test_a_tilde_spelling_is_refused_though_sqlite_would_not_expand_it(operator_dir, monkeypatch):
    """SQLite does not expand `~`: it would look under a directory literally named `~` in the
    working directory. A test that spells the store that way meant the operator's."""
    monkeypatch.setenv("HOME", str(operator_dir.parent))
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect("~/.ibkr_core/store.db")


@pytest.mark.parametrize(
    "database",
    [":memory:", "", "file::memory:?cache=shared", "file:?mode=memory", 42, None],
    ids=["memory", "empty", "shared-memory-uri", "pathless-uri", "not-a-path", "none"],
)
def test_a_database_that_names_no_file_there_is_not_judged_to(operator_dir, database):
    """In-memory and pathless databases, and values that are no path at all, name no place."""
    assert conftest._operator_path(database, database=True) is None


@pytest.mark.parametrize(
    "uri",
    ["file://[x/elsewhere.db", "file://somehost<dir>/store.db"],
    ids=["bracket", "a-host-before-the-directory"],
)
def test_an_authority_sqlite_refuses_is_left_to_sqlite(operator_dir, uri):
    """SQLite opens nothing for a URI whose authority is neither empty nor `localhost`, and
    says so in its own words — even when the path after it lies in the directory. The guard
    must not answer first: `urllib` raised on the `[`."""
    with pytest.raises(sqlite3.OperationalError, match="invalid uri authority"):
        sqlite3.connect(uri.replace("<dir>", str(operator_dir)), uri=True)


@pytest.mark.parametrize(
    ("name", "error"),
    [("store\x00.db", ValueError), ("store\ud800.db", UnicodeEncodeError)],
    ids=["nul", "lone-surrogate"],
)
def test_a_name_no_file_system_can_hold_is_refused_by_sqlite_itself(operator_dir, name, error):
    """The guard cannot resolve these and answers None; `sqlite3.connect` refuses them in its
    own words, and nothing opens. A guard that raised instead would answer from inside the
    audit hook — the old judge caught `OSError` and `RuntimeError` around `resolve()`, not the
    `ValueError` these raise (claudia_ui plan § 13, item 13). The two errors read the same, so
    the traceback is what tells them apart."""
    with pytest.raises(error) as caught:
        sqlite3.connect(str(operator_dir / name))
    frames = [frame.name for frame in traceback.extract_tb(caught.value.__traceback__)]
    assert "_operator_data_hook" not in frames, "the guard answered, not SQLite"


def test_a_database_elsewhere_is_not_refused(operator_dir, tmp_path):
    """Only the directory itself is guarded — not a sibling whose name merely starts like it."""
    for elsewhere in (
        tmp_path / "elsewhere" / "store.db",
        tmp_path / ".ibkr_core_backup" / "store.db",
    ):
        elsewhere.parent.mkdir()
        sqlite3.connect(elsewhere).close()
        sqlite3.connect(f"{elsewhere.as_uri()}?mode=ro", uri=True).close()
    # A URI's path ends at `?` or `#`: what follows never names the file, even when it spells
    # a way back into the directory.
    fragment = f"{(tmp_path / 'elsewhere' / 'store.db').as_uri()}?mode=ro#/../../.ibkr_core/store.db"
    sqlite3.connect(fragment, uri=True).close()


ROUTES = {
    "sqlite3.connect": lambda p: sqlite3.connect(p),
    "a reference taken at import": lambda p: CAPTURED_CONNECT(p),
    "sqlite3.Connection": lambda p: sqlite3.Connection(p),
    "sqlite3.dbapi2.connect": lambda p: sqlite3.dbapi2.connect(p),
    "_sqlite3.connect": lambda p: importlib.import_module("_sqlite3").connect(p),
}


@pytest.mark.parametrize("route", ROUTES)
def test_every_route_to_sqlite_is_refused(operator_dir, route):
    """SQLite's audit event fires inside the connection, whatever called it. The swapped
    `sqlite3.connect` it replaced saw one name of five."""
    before = _state(operator_dir)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        ROUTES[route](operator_dir / "new.db")
    assert _state(operator_dir) == before


def _open_for_writing(d: Path) -> None:
    """`os.open`, the lowest-level way in."""
    os.close(os.open(d / "new.bin", os.O_CREAT | os.O_WRONLY, 0o600))


def _rename_in(d: Path) -> None:
    """A file made beside the directory, renamed into it."""
    source = d.parent / "made-outside.txt"
    source.write_text("x")
    os.rename(source, d / "renamed.txt")


def _move_in(d: Path) -> None:
    """A file made beside the directory, moved into it."""
    source = d.parent / "made-outside-too.txt"
    source.write_text("x")
    shutil.move(source, d / "moved.txt")


def _temporary_file_there(d: Path) -> None:
    """A temporary file created in the directory."""
    with tempfile.NamedTemporaryFile(dir=d):
        pass


FILE_OPERATIONS = {
    "read the Drive token": lambda d: (d / "token.json").read_text(),
    "write the Drive token": lambda d: (d / "token.json").write_text("{}"),
    "create a file": lambda d: (d / "new.json").write_text("{}"),
    "os.open": _open_for_writing,
    "make a directory": lambda d: (d / "sub").mkdir(),
    "change its mode": lambda d: d.chmod(0o700),
    "touch a timestamp": lambda d: os.utime(d / "token.json"),
    "remove the token": lambda d: (d / "token.json").unlink(),
    "rename a file in": _rename_in,
    "move a file in": _move_in,
    "copy the store out": lambda d: shutil.copyfile(d / "store.db", d.parent / "copied.db"),
    "copy a file in": lambda d: shutil.copyfile(__file__, d / "copied.py"),
    "hard-link the store out": lambda d: os.link(d / "store.db", d.parent / "linked.db"),
    "a temporary file there": _temporary_file_there,
    "remove the whole tree": lambda d: shutil.rmtree(d),
}


@pytest.mark.parametrize("operation", FILE_OPERATIONS)
def test_every_file_operation_there_is_refused_before_it_happens(operator_dir, operation):
    """The Drive token, the credentials, the browser profiles: any file under the directory,
    read or written, is refused before the operation, and nothing there changes."""
    before = _state(operator_dir)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        FILE_OPERATIONS[operation](operator_dir)
    assert _state(operator_dir) == before
    assert not (operator_dir.parent / "copied.db").exists()
    assert not (operator_dir.parent / "linked.db").exists()


def test_the_store_itself_is_refused_before_it_touches_the_directory(operator_dir):
    """The route a test takes by accident: `SQLiteStore`, whose constructor makes and restricts
    its directory before `initialize()` connects. The swapped `connect` refused only at the
    connect — after the directory's mode had changed."""
    from dataclasses import replace

    from ibkr_core_mcp import SQLiteStore
    from ibkr_core_mcp.config import Config

    before = _state(operator_dir)
    config = replace(Config.from_env(), sqlite_path=operator_dir / "second.db")
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        SQLiteStore(config).initialize()
    assert _state(operator_dir) == before


def test_the_refusal_cannot_be_swallowed_by_code_that_catches_exception(operator_dir):
    """`flex_sync`'s never-raise readers catch `UNOPENABLE` around their opens — every member
    an `Exception` subclass; a refusal they could catch would read as "dataset unreadable"
    instead of failing the test."""
    assert not issubclass(pytest.fail.Exception, Exception)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        try:
            (operator_dir / "token.json").read_text()
        except Exception:  # what a never-raise reader does
            pytest.fail("the refusal was caught by `except Exception`")


def test_a_refusal_swallowed_in_a_thread_still_fails_the_run(operator_dir, monkeypatch):
    """A refusal raised in a thread fails no test, and `except BaseException` would hide one
    anywhere; so every refusal of the real directory is recorded, and `pytest_sessionfinish`
    fails the run for it. Here the stand-in plays the real directory, with a list of its own."""
    monkeypatch.setattr(conftest, "_REAL_OPERATOR_DATA_DIR", operator_dir)
    monkeypatch.setattr(conftest, "_operator_refusals", [])
    swallowed: list[BaseException] = []

    def careless_worker():
        """Open the store in a thread, and swallow whatever happens."""
        try:
            sqlite3.connect(operator_dir / "store.db")
        except BaseException as exc:
            swallowed.append(exc)

    worker = threading.Thread(target=careless_worker)
    worker.start()
    worker.join()

    assert len(swallowed) == 1 and isinstance(swallowed[0], pytest.fail.Exception)
    assert conftest._operator_refusals == [f"sqlite3.connect {operator_dir / 'store.db'}"]
    assert conftest._refusal_violations(conftest._operator_refusals)


def test_a_refusal_of_a_stand_in_is_not_recorded_as_the_real_directory(operator_dir):
    """Only the real directory's refusals fail the run at session end: the tests in this file
    refuse stand-ins on purpose, and a record of those would fail every run."""
    before = list(conftest._operator_refusals)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(operator_dir / "store.db")
    assert conftest._operator_refusals == before


def test_the_session_end_check_names_every_refusal():
    """A refusal of the operator's directory is a violation of its own, one line each — the
    refusal stopped the operation, and this is what fails the run when a test hid it."""
    violations = conftest._refusal_violations(["open /x/token.json", "sqlite3.connect /x/store.db"])
    assert len(violations) == 2
    assert "open /x/token.json" in violations[0]
    assert conftest._refusal_violations([]) == []


# ── Integration tests are exempt, by design ────────────────────────────────────────────────
#
# They run against the operator's live gateway and configured store, which is their subject.
# The gates run `-m "not integration"`, so the exemption matters only to a live run; it must
# still cover every fixture scope, because `live_client` is module-scoped (the pytest-socket
# lesson in `tests/conftest.py`).


def test_an_integration_test_is_exempt_from_its_setup_to_its_teardown(operator_dir):
    """Between the runtest hooks for an `integration` item the guard is disarmed — the store
    and the token open — and it is armed again once the item is torn down."""
    item = _item("integration")
    conftest.pytest_runtest_setup(item)
    try:
        sqlite3.connect(operator_dir / "store.db").close()
        assert (operator_dir / "token.json").read_text() == '{"token": "stand-in"}'
    finally:
        conftest.pytest_runtest_teardown(item, None)
    with pytest.raises(pytest.fail.Exception, match="operator's data"):
        sqlite3.connect(operator_dir / "store.db")


def test_a_unit_test_is_not_exempt(operator_dir):
    """The same hooks leave the guard armed for an item without the marker."""
    item = _item("security")
    conftest.pytest_runtest_setup(item)
    try:
        with pytest.raises(pytest.fail.Exception, match="operator's data"):
            sqlite3.connect(operator_dir / "store.db")
    finally:
        conftest.pytest_runtest_teardown(item, None)


def test_the_exemption_brackets_every_fixture_scope():
    """The disarm runs before the runner fills fixtures and the re-arm after it tears them down
    (`tryfirst` / `trylast`): an integration module's module-scoped `live_client` is set up and
    torn down inside the exemption, not at its edges."""
    setup_opts = getattr(conftest.pytest_runtest_setup, "pytest_impl")  # noqa: B009 — pluggy's marker attribute
    teardown_opts = getattr(conftest.pytest_runtest_teardown, "pytest_impl")  # noqa: B009
    assert setup_opts["tryfirst"] is True
    assert teardown_opts["trylast"] is True


def test_a_temporary_database_and_file_still_open(tmp_path):
    """The guard is a refusal for one directory, not a block on SQLite or on files."""
    conn = sqlite3.connect(tmp_path / "scratch.db")
    try:
        conn.execute("CREATE TABLE t (x)")
    finally:
        conn.close()
    (tmp_path / "scratch.txt").write_text("fine")
    assert (tmp_path / "scratch.db").exists() and (tmp_path / "scratch.txt").exists()
