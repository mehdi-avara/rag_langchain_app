from datetime import date

import pytest

from shared.reporting.services import (
    ReportingValidationError,
    normalize_group_by,
    validate_date_range,
)


def test_validate_date_range_rejects_inverted_range():
    with pytest.raises(ReportingValidationError):
        validate_date_range(
            date(2026, 6, 22),
            date(2026, 6, 21),
        )


def test_normalize_group_by_uses_default_and_rejects_unknown_value():
    assert normalize_group_by(
        None,
        {"supplier", "month"},
        "supplier",
    ) == "supplier"

    assert normalize_group_by(
        "MONTH",
        {"supplier", "month"},
        "supplier",
    ) == "month"

    with pytest.raises(ReportingValidationError):
        normalize_group_by(
            "day",
            {"supplier", "month"},
            "supplier",
        )
