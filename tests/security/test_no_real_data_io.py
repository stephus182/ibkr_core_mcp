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
