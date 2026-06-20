from decimal import Decimal
from types import SimpleNamespace

from supplier_management.services import (
    calculate_supplier_performance,
    supplier_searchable_text,
)


def test_supplier_performance_averages_available_scores():
    evaluations = [
        SimpleNamespace(
            quality_score=Decimal("80"),
            delivery_score=Decimal("90"),
            price_score=None,
            service_score=Decimal("70"),
        ),
        SimpleNamespace(
            quality_score=Decimal("100"),
            delivery_score=Decimal("70"),
            price_score=Decimal("60"),
            service_score=None,
        ),
    ]

    result = calculate_supplier_performance(12, evaluations)

    assert result.supplier_id == 12
    assert result.evaluation_count == 2
    assert result.quality_score == Decimal("90.00")
    assert result.delivery_score == Decimal("80.00")
    assert result.price_score == Decimal("60.00")
    assert result.service_score == Decimal("70.00")
    assert result.overall_score == Decimal("75.00")


def test_supplier_searchable_text_contains_supplier_contacts_and_categories():
    supplier = SimpleNamespace(
        code="SUP-001",
        name="Atlas Industrial",
        supplier_type="manufacturer",
        country="Iran",
        city="Tehran",
        address=None,
        tax_id=None,
        website=None,
        status="approved",
        notes="Valve manufacturer",
        contacts=[
            SimpleNamespace(
                full_name="Ali Rezaei",
                job_title="Sales",
                phone="09120000000",
                email="sales@example.com",
                notes=None,
            )
        ],
        categories=[
            SimpleNamespace(category="Valves"),
            SimpleNamespace(category="Piping"),
        ],
    )

    text = supplier_searchable_text(supplier)

    assert "Atlas Industrial" in text
    assert "Ali Rezaei" in text
    assert "Valves" in text
    assert "Piping" in text
