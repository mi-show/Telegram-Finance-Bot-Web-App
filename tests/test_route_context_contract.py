import pytest

from app.handlers import common
from app.handlers.route_context import ROUTE_CONTEXT_EXPORTS, build_route_context


def test_build_route_context_rejects_missing_symbol():
    source = {name: object() for name in ROUTE_CONTEXT_EXPORTS if name != "_t"}

    with pytest.raises(RuntimeError, match="route_ctx contract mismatch"):
        build_route_context(source)


def test_build_route_context_keeps_only_contract_symbols():
    source = {name: object() for name in ROUTE_CONTEXT_EXPORTS}
    source["__extra__"] = object()

    ctx = build_route_context(source)

    assert set(vars(ctx)) == set(ROUTE_CONTEXT_EXPORTS)


def test_common_route_ctx_matches_declared_contract():
    expected = set(common.ROUTE_CONTEXT_EXPORTS)
    actual = set(vars(common.route_ctx))

    assert actual == expected
