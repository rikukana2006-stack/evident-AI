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
        "tax_adjusted_match": 0,
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
    assert result.summary["tax_adjusted_match"] == 2
    assert [(diff.field, diff.status) for diff in result.line_comparisons[0].differences] == [
        ("unit_price", "tax_adjusted_match"),
        ("amount", "tax_adjusted_match"),
    ]


def test_matching_flags_invoice_items_without_delivery_note() -> None:
    delivery = ExtractedDocument.model_validate(
        {
            "document_type": "delivery_note",
            "vendor_name": "Supplier",
            "document_date": "2026-07-10",
            "document_number": "DN-100",
            "items": [],
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
                    "item_name": "未納品請求品",
                    "quantity": 1,
                    "unit_price": 5000,
                    "amount": 5000,
                    "tax_rate": 10,
                }
            ],
        }
    )

    result = compare_documents("delivery-id", "invoice-id", delivery, invoice)

    assert result.status == "review_required"
    assert result.summary["missing_delivery_item"] == 1
    assert result.line_comparisons[0].status == "missing_delivery_item"


def test_matching_pairs_ocr_damaged_names_when_numbers_match() -> None:
    delivery = ExtractedDocument.model_validate(
        {
            "document_type": "delivery_note",
            "vendor_name": "ヘルシーフード",
            "document_date": "2026-06-01",
            "document_number": "DN-100",
            "items": [
                {
                    "item_name": "Nigat日 薬 明治アトアサポートゼリー食料品 ２Ｏ０Ｅ×２４",
                    "quantity": 1,
                    "unit_price": 3240,
                    "amount": 3240,
                    "tax_rate": 8,
                }
            ],
        }
    )
    invoice = ExtractedDocument.model_validate(
        {
            "document_type": "invoice",
            "vendor_name": "ヘルシーフード",
            "document_date": "2026-06-30",
            "document_number": "INV-100",
            "items": [
                {
                    "item_name": "メ明治アクアサポートゼリー 200g×24",
                    "quantity": 1,
                    "unit_price": 3240,
                    "amount": 3240,
                    "tax_rate": 8,
                }
            ],
        }
    )

    result = compare_documents("delivery-id", "invoice-id", delivery, invoice)

    assert result.summary["missing_invoice_item"] == 0
    assert result.summary["missing_delivery_item"] == 0
    assert result.line_comparisons[0].status == "name_check_required"
    assert result.line_comparisons[0].invoice_item is not None


def test_matching_pairs_amount_match_as_review_candidate_instead_of_missing() -> None:
    delivery = ExtractedDocument.model_validate(
        {
            "document_type": "delivery_note",
            "vendor_name": "ヘルシーフード",
            "document_date": "2026-06-01",
            "document_number": "DN-101",
            "items": [
                {
                    "item_name": "Hiigata シで 手んしレモも国味京鶏品",
                    "quantity": 36,
                    "unit_price": 104,
                    "amount": 3744,
                    "tax_rate": 8,
                }
            ],
        }
    )
    invoice = ExtractedDocument.model_validate(
        {
            "document_type": "invoice",
            "vendor_name": "ヘルシーフード",
            "document_date": "2026-06-30",
            "document_number": "INV-101",
            "items": [
                {
                    "item_name": "のみや水ほんのリレモン風味",
                    "quantity": 150,
                    "unit_price": 3744,
                    "amount": 3744,
                    "tax_rate": 8,
                }
            ],
        }
    )

    result = compare_documents("delivery-id", "invoice-id", delivery, invoice)

    assert result.summary["missing_invoice_item"] == 0
    assert result.summary["missing_delivery_item"] == 0
    assert result.line_comparisons[0].status == "name_check_required"
