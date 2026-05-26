import pytest


def test_config_has_flex_fields(mock_config):
    assert hasattr(mock_config, "flex_token")
    assert hasattr(mock_config, "flex_query_id")


def test_flex_query_error_is_ibkr_core_error():
    from ibkr_core_mcp.exceptions import FlexQueryError, IBKRCoreError
    err = FlexQueryError("failed")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "failed"


def test_flex_query_error_exported_from_package():
    from ibkr_core_mcp import FlexQueryError
    from ibkr_core_mcp.exceptions import FlexQueryError as _internal
    assert FlexQueryError is _internal
