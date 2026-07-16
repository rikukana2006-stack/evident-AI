import csv
from io import StringIO


STATUS_LABELS = {
    "matched": "一致",
    "different": "差異あり",
    "name_check_required": "品名確認",
    "tax_adjusted_match": "税抜/税込換算で一致",
    "missing_invoice_item": "請求書に不足",
    "missing_delivery_item": "納品書に不足",
    "review_required": "確認待ち",
    "approved": "承認済み",
    "held": "保留",
    "rejected": "却下",
}

FIELD_LABELS = {
    "item_name": "品名",
    "quantity": "数量",
    "unit_price": "単価",
    "amount": "金額",
    "tax_rate": "税率",
}


def label_status(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def label_field(field: str) -> str:
    return FIELD_LABELS.get(field, field)


def matching_result_to_csv(result: dict) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["明細判定", "項目", "納品書", "請求書", "差分判定"])

    for line in result["line_comparisons"]:
        if not line["differences"]:
            writer.writerow([label_status(line["status"]), "", "", "", "一致"])
            continue
        for diff in line["differences"]:
            writer.writerow(
                [
                    label_status(line["status"]),
                    label_field(diff["field"]),
                    diff.get("delivery_value") or "",
                    diff.get("invoice_value") or "",
                    label_status(diff["status"]),
                ]
            )

    return output.getvalue()
