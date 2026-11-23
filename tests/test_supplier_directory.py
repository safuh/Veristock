"""Supplier master-data and supplier catalogue input validation tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from veristock.api.suppliers import SupplierItemWrite, SupplierWrite
from veristock.inventory.models import Supplier, SupplierItem


def test_supplier_write_normalizes_expected_tenant_master_data_shape():
    supplier = SupplierWrite(
        code="SUP-001",
        name="  Regional Foods Ltd  ",
        email="orders@example.test",
        phone="+254700000000",
        default_currency="KES",
    )
    assert supplier.code == "SUP-001"
    assert supplier.name == "  Regional Foods Ltd  "
    assert supplier.default_currency == "KES"
    assert "organization_id" not in supplier.model_dump()


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "x", "name": "Valid Supplier"},
        {"code": "SUP-1", "name": "Valid Supplier", "default_currency": "K"},
        {"code": "SUP-1", "name": "Valid Supplier", "status": "deleted"},
    ],
)
def test_supplier_write_rejects_invalid_identifiers_currency_and_status(payload):
    with pytest.raises(ValidationError):
        SupplierWrite(**payload)


def test_supplier_item_rejects_negative_cost_and_zero_order_quantity():
    with pytest.raises(ValidationError):
        SupplierItemWrite(unit_cost=Decimal("-0.01"))
    with pytest.raises(ValidationError):
        SupplierItemWrite(unit_cost=Decimal("10"), minimum_order_quantity=Decimal("0"))


def test_supplier_catalogue_models_have_tenant_uniqueness_and_database_checks():
    supplier_constraints = {constraint.name for constraint in Supplier.__table__.constraints}
    item_constraints = {constraint.name for constraint in SupplierItem.__table__.constraints}
    assert "uq_suppliers_org_code" in supplier_constraints
    assert "ck_suppliers_status" in supplier_constraints
    assert "uq_supplier_items_scope" in item_constraints
    assert "ck_supplier_items_nonnegative_cost" in item_constraints
    assert "ck_supplier_items_positive_moq" in item_constraints
