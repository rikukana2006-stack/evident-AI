from app.matching import compare_documents
from app.mock_ocr import DEMO_DELIVERY_NOTE, DEMO_INVOICE
from app.schemas import ExtractedDocument


def test_demo_matching_flags_expected_differences() -> None:
    result = compare_documents(
        "delivery-id",
        "invoice-id",
        ExtractedDocument.model_validate(DEMO_DELIVERY_NOTE),
        ExtractedDocument.model_validate(DEMO_INVOICE),
    )

    assert result.status == "review_required"
    assert result.summary == {
        "matched": 0,
        "different": 1,
        "name_check_required": 1,
        "missing_invoice_item": 0,
        "missing_delivery_item": 0,
    }

    milk, bread = result.line_comparisons

    assert milk.status == "name_check_required"
    assert [(diff.field, diff.status) for diff in milk.differences] == [
        ("item_name", "name_check_required"),
        ("quantity", "different"),
        ("amount", "different"),
    ]

    assert bread.status == "different"
    assert [(diff.field, diff.status) for diff in bread.differences] == [
        ("unit_price", "different"),
        ("amount", "different"),
    ]


def test_matching_accepts_tax_exclusive_delivery_against_tax_inclusive_invoice() -> None:
    delivery = ExtractedDocument.model_validate(
        {
            "document_type": "delivery_note",
            "vendor_name": "Supplier",
            "document_date": "2026-07-10",
            "document_number": "DN-100",
            "items": [
                {
                    "item_name": "病院用ハイター5kg",
                    "quantity": 1,
                    "unit_price": 3360,
                    "amount": 3360,
                    "tax_rate": 10,
                }
            ],
        }
    )
    invoice = ExtractedDocument.model_validate(
        {
            "document_type": "invoice",
            "vendor_name": "Supplier",
            "document_date": "2026-07-31",
            "document_number": "INV-100",
            "items": [
                {
                    "item_name": "病院用ハイター5kg",
                    "quantity": 1,
                    "unit_price": 3696,
                    "amount": 3696,
                    "tax_rate": 10,
                }
            ],
        }
    )

    result = compare_documents("delivery-id", "invoice-id", delivery, invoice)

    assert result.status == "matched"
    assert result.summary["matched"] == 1
    assert result.line_comparisons[0].differences == []
