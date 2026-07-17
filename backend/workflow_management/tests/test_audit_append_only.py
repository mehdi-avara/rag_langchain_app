import pytest

from workflow_management.models import (
    _prevent_workflow_audit_mutation,
)


def test_workflow_audit_mutation_is_rejected():
    with pytest.raises(
        ValueError,
        match="append-only",
    ):
        _prevent_workflow_audit_mutation()
