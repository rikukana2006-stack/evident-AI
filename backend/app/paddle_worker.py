import json
import sys
from pathlib import Path
from typing import Any

from app.vision_ocr import configure_paddle_cache, get_paddle_ocr, run_paddle_prediction


def to_json_safe(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return to_json_safe(value.tolist())
    if isinstance(value, dict):
        return {str(key): to_json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(nested) for nested in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python -m app.paddle_worker <input.json> <output.json>", file=sys.stderr)
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    image_paths = [Path(path) for path in payload.get("images", [])]

    configure_paddle_cache()
    ocr = get_paddle_ocr()
    results = [to_json_safe(run_paddle_prediction(ocr, image_path)) for image_path in image_paths]
    output_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
