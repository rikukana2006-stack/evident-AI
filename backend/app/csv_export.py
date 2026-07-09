import csv
from io import StringIO


def matching_result_to_csv(result: dict) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["line_status", "field", "delivery_value", "invoice_value", "difference_status"])

    for line in result["line_comparisons"]:
        if not line["differences"]:
            writer.writerow([line["status"], "", "", "", "matched"])
            continue
        for diff in line["differences"]:
            writer.writerow(
                [
                    line["status"],
                    diff["field"],
                    diff.get("delivery_value") or "",
                    diff.get("invoice_value") or "",
                    diff["status"],
                ]
            )

    return output.getvalue()
