from ibkr_core_mcp.exceptions import IBKRCoreError, HumanAuthError
from ibkr_core_mcp import HumanAuthError as _HumanAuthErrorPublic


def test_human_auth_error_is_ibkr_core_error():
    err = HumanAuthError("denied")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "denied"


def test_human_auth_error_exported_from_package():
    assert _HumanAuthErrorPublic is HumanAuthError
