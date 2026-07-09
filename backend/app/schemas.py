from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


DocumentType = Literal["delivery_note", "invoice"]


class Item(BaseModel):
    item_name: str
    quantity: Decimal = Field(ge=0)
    unit_price: Decimal = Field(ge=0)
    amount: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(ge=0)


class ExtractedDocument(BaseModel):
    document_type: DocumentType
    vendor_name: str
    document_date: str
    document_number: str
    ocr_note: str | None = None
    items: list[Item]


class DocumentResponse(BaseModel):
    id: str
    document_type: str
    original_filename: str
    status: str
    ocr_data: ExtractedDocument | None = None


class DocumentUpdateRequest(BaseModel):
    ocr_data: ExtractedDocument


class MatchingRunRequest(BaseModel):
    delivery_document_id: str
    invoice_document_id: str


class FieldDifference(BaseModel):
    field: str
    delivery_value: str | None
    invoice_value: str | None
    status: Literal["matched", "different", "name_check_required"]


class LineComparison(BaseModel):
    delivery_item: Item | None
    invoice_item: Item | None
    status: Literal["matched", "different", "name_check_required", "missing_invoice_item", "missing_delivery_item"]
    differences: list[FieldDifference]


class MatchingResult(BaseModel):
    matching_id: str | None = None
    status: Literal["matched", "review_required", "approved", "held", "rejected"]
    delivery_document_id: str
    invoice_document_id: str
    line_comparisons: list[LineComparison]
    summary: dict[str, int]
