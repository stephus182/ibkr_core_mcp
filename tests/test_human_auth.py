from ibkr_core_mcp.exceptions import IBKRCoreError, HumanAuthError


def test_human_auth_error_is_ibkr_core_error():
    err = HumanAuthError("denied")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "denied"
