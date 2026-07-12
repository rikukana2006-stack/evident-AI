from difflib import SequenceMatcher
from decimal import Decimal, ROUND_HALF_UP

from app.schemas import ExtractedDocument, FieldDifference, LineComparison, MatchingResult


def normalize_name(value: str) -> str:
    return "".join(value.casefold().split())


def name_similarity(left: str, right: str) -> float:
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return 0.9
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def values_match(left: object, right: object) -> bool:
    return str(left) == str(right)


def round_yen(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def tax_multiplier(tax_rate: object) -> Decimal:
    return Decimal("1") + (Decimal(str(tax_rate)) / Decimal("100"))


def numeric_values_match(left: object, right: object, tolerance: Decimal = Decimal("1")) -> bool:
    return abs(Decimal(str(left)) - Decimal(str(right))) <= tolerance


def price_match_status(delivery_value: object, invoice_value: object, tax_rate: object) -> str:
    if numeric_values_match(delivery_value, invoice_value, Decimal("0")):
        return "matched"

    delivery_amount = Decimal(str(delivery_value))
    invoice_amount = Decimal(str(invoice_value))
    multiplier = tax_multiplier(tax_rate)

    # Suppliers often put tax-exclusive prices on delivery notes and tax-inclusive
    # prices on invoices. Treat those as equivalent so reviewers focus on real
    # business differences instead of display-format differences.
    delivery_as_tax_included = round_yen(delivery_amount * multiplier)
    invoice_as_tax_included = round_yen(invoice_amount * multiplier)
    if numeric_values_match(delivery_as_tax_included, invoice_amount) or numeric_values_match(
        invoice_as_tax_included,
        delivery_amount,
    ):
        return "tax_adjusted_match"
    return "different"


def compare_documents(
    delivery_document_id: str,
    invoice_document_id: str,
    delivery: ExtractedDocument,
    invoice: ExtractedDocument,
) -> MatchingResult:
    comparisons: list[LineComparison] = []
    used_invoice_indexes: set[int] = set()

    for delivery_item in delivery.items:
        best_index = -1
        best_score = 0.0
        for index, invoice_item in enumerate(invoice.items):
            if index in used_invoice_indexes:
                continue
            score = name_similarity(delivery_item.item_name, invoice_item.item_name)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index == -1 or best_score < 0.55:
            comparisons.append(
                LineComparison(
                    delivery_item=delivery_item,
                    invoice_item=None,
                    status="missing_invoice_item",
                    differences=[
                        FieldDifference(
                            field="item_name",
                            delivery_value=delivery_item.item_name,
                            invoice_value=None,
                            status="different",
                        )
                    ],
                )
            )
            continue

        used_invoice_indexes.add(best_index)
        invoice_item = invoice.items[best_index]
        differences: list[FieldDifference] = []

        # Similar names are intentionally routed to human review, because OCR and supplier naming
        # variations can hide real business mismatches.
        if delivery_item.item_name == invoice_item.item_name:
            name_status = "matched"
        elif best_score >= 0.55:
            name_status = "name_check_required"
        else:
            name_status = "different"

        if name_status != "matched":
            differences.append(
                FieldDifference(
                    field="item_name",
                    delivery_value=delivery_item.item_name,
                    invoice_value=invoice_item.item_name,
                    status=name_status,
                )
            )

        for field in ("quantity", "unit_price", "amount", "tax_rate"):
            delivery_value = getattr(delivery_item, field)
            invoice_value = getattr(invoice_item, field)
            if field in {"unit_price", "amount"}:
                field_status = price_match_status(delivery_value, invoice_value, delivery_item.tax_rate)
            else:
                field_status = "matched" if values_match(delivery_value, invoice_value) else "different"

            if field_status != "matched":
                differences.append(
                    FieldDifference(
                        field=field,
                        delivery_value=str(delivery_value),
                        invoice_value=str(invoice_value),
                        status=field_status,
                    )
                )

        if any(diff.status == "name_check_required" for diff in differences):
            line_status = "name_check_required"
        elif any(diff.status == "different" for diff in differences):
            line_status = "different"
        else:
            line_status = "matched"

        comparisons.append(
            LineComparison(
                delivery_item=delivery_item,
                invoice_item=invoice_item,
                status=line_status,
                differences=differences,
            )
        )

    for index, invoice_item in enumerate(invoice.items):
        if index in used_invoice_indexes:
            continue
        comparisons.append(
            LineComparison(
                delivery_item=None,
                invoice_item=invoice_item,
                status="missing_delivery_item",
                differences=[
                    FieldDifference(
                        field="item_name",
                        delivery_value=None,
                        invoice_value=invoice_item.item_name,
                        status="different",
                    )
                ],
            )
        )

    summary = {
        "matched": sum(1 for item in comparisons if item.status == "matched"),
        "different": sum(1 for item in comparisons if item.status == "different"),
        "name_check_required": sum(1 for item in comparisons if item.status == "name_check_required"),
        "missing_invoice_item": sum(1 for item in comparisons if item.status == "missing_invoice_item"),
        "missing_delivery_item": sum(1 for item in comparisons if item.status == "missing_delivery_item"),
        "tax_adjusted_match": sum(
            1
            for item in comparisons
            for diff in item.differences
            if diff.status == "tax_adjusted_match"
        ),
    }

    return MatchingResult(
        status="matched" if len(comparisons) == summary["matched"] else "review_required",
        delivery_document_id=delivery_document_id,
        invoice_document_id=invoice_document_id,
        line_comparisons=comparisons,
        summary=summary,
    )
