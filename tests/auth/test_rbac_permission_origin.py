"""Invalid role tokens remain denied and identify their source for operators."""

import logging

from ai_karen_engine.auth import rbac_middleware as rbac


def test_invalid_claim_tokens_log_origin_without_granting_role(caplog):
    with caplog.at_level(logging.WARNING):
        granted = rbac._resolve_permission_names(
            ["admin", "user", "read"], source="authenticated_permission_claims"
        )
    assert granted == {rbac.Permission.READ}
    assert "origin=authenticated_permission_claims" in caplog.text
    assert "Unrecognized RBAC permission 'admin'" in caplog.text


def test_invalid_config_tokens_log_role_source(caplog):
    with caplog.at_level(logging.WARNING):
        granted = rbac._resolve_permission_names(
            ["admin"], source="role_config:user"
        )
    assert granted == set()
    assert "origin=role_config:user" in caplog.text
