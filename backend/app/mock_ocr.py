from app.schemas import ExtractedDocument


DEMO_DELIVERY_NOTE = {
    "document_type": "delivery_note",
    "vendor_name": "〇〇食品株式会社",
    "document_date": "2026-07-09",
    "document_number": "DN-001",
    "items": [
        {
            "item_name": "明治おいしい牛乳",
            "quantity": 20,
            "unit_price": 100,
            "amount": 2000,
            "tax_rate": 8,
        },
        {
            "item_name": "パン",
            "quantity": 30,
            "unit_price": 80,
            "amount": 2400,
            "tax_rate": 8,
        },
    ],
}

DEMO_INVOICE = {
    "document_type": "invoice",
    "vendor_name": "〇〇食品株式会社",
    "document_date": "2026-07-31",
    "document_number": "INV-001",
    "items": [
        {
            "item_name": "おいしい牛乳",
            "quantity": 18,
            "unit_price": 100,
            "amount": 1800,
            "tax_rate": 8,
        },
        {
            "item_name": "パン",
            "quantity": 30,
            "unit_price": 90,
            "amount": 2700,
            "tax_rate": 8,
        },
    ],
}


def run_mock_ocr(document_type: str) -> ExtractedDocument:
    if document_type == "delivery_note":
        return ExtractedDocument.model_validate(DEMO_DELIVERY_NOTE)
    return ExtractedDocument.model_validate(DEMO_INVOICE)
