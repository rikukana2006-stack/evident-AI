from dataclasses import dataclass
from pathlib import Path

from app.schemas import ExtractedDocument


@dataclass(frozen=True)
class VendorProfile:
    profile_id: str
    display_name: str
    aliases: tuple[str, ...]
    layout_profile_name: str
    minimum_expected_items: int


GENERIC_PROFILE = VendorProfile(
    profile_id="generic",
    display_name="未判定の取引先",
    aliases=(),
    layout_profile_name="汎用OCRレイアウト",
    minimum_expected_items=1,
)


VENDOR_PROFILES = (
    VendorProfile(
        profile_id="mizuno_sangyo",
        display_name="水野産業",
        aliases=("水野産業", "水野請求書", "水野納品書", "mizuno"),
        layout_profile_name="水野産業 標準明細レイアウト",
        minimum_expected_items=1,
    ),
    VendorProfile(
        profile_id="sato_kyozai",
        display_name="サトウ教材",
        aliases=("サトウ教材", "サトウ", "sato"),
        layout_profile_name="サトウ教材 標準明細レイアウト",
        minimum_expected_items=3,
    ),
    VendorProfile(
        profile_id="healthy_food",
        display_name="ヘルシーフード",
        aliases=("ヘルシーフード", "healthy food", "healthyfood"),
        layout_profile_name="ヘルシーフード 標準明細レイアウト",
        minimum_expected_items=5,
    ),
    VendorProfile(
        profile_id="shimakyu",
        display_name="シマキュウ",
        aliases=("シマキュウ", "ｼﾏｷｭｳ", "シマキュー", "shimakyu"),
        layout_profile_name="シマキュウ標準明細レイアウト",
        minimum_expected_items=5,
    ),
)


def normalize_profile_text(value: str) -> str:
    return "".join(str(value or "").casefold().split())


def detect_vendor_profile(filename: str, vendor_name: str = "", raw_text: str = "") -> VendorProfile:
    haystack = normalize_profile_text(f"{Path(filename).stem} {vendor_name} {raw_text[:1000]}")
    for profile in VENDOR_PROFILES:
        if any(normalize_profile_text(alias) in haystack for alias in profile.aliases):
            return profile
    return GENERIC_PROFILE


def estimate_ocr_confidence(document: ExtractedDocument, profile: VendorProfile) -> float:
    score = 0.25
    if document.items:
        score += 0.25
    if len(document.items) >= profile.minimum_expected_items:
        score += 0.2
    if document.vendor_name:
        score += 0.1
    if document.document_number:
        score += 0.1
    if profile.profile_id != "generic":
        score += 0.1
    if document.ocr_note and not document.items:
        score -= 0.2
    return max(0, min(1, round(score, 2)))


def build_ocr_warnings(document: ExtractedDocument, profile: VendorProfile) -> list[str]:
    warnings: list[str] = []
    if profile.profile_id == "generic":
        warnings.append("未知の取引先として汎用ルールで抽出しました。読み取り結果を確認してください。")
    if not document.items:
        warnings.append("明細行を抽出できませんでした。PDFの画質または帳票レイアウトを確認してください。")
    elif len(document.items) < profile.minimum_expected_items:
        warnings.append("想定より明細行が少ない可能性があります。複数ページの読み取り漏れを確認してください。")
    if any(item.amount <= 0 for item in document.items):
        warnings.append("金額が0円の明細があります。OCRの列認識を確認してください。")
    return warnings


def is_placeholder_vendor_name(value: str) -> bool:
    normalized = normalize_profile_text(value)
    return normalized in {"", "未設定", "譛ｪ險ｭ螳"}


def enrich_extracted_document(
    document: ExtractedDocument,
    filename: str,
    raw_text: str = "",
) -> ExtractedDocument:
    profile = detect_vendor_profile(filename, document.vendor_name, raw_text)
    confidence = estimate_ocr_confidence(document, profile)
    warnings = build_ocr_warnings(document, profile)
    vendor_name = document.vendor_name
    if profile.profile_id != "generic" and is_placeholder_vendor_name(vendor_name):
        vendor_name = profile.display_name
    items = document.items
    if profile.profile_id == "healthy_food":
        # Healthy Food marks reduced-tax items with a star. OCR frequently drops
        # or misreads that mark, so default this vendor's extracted lines to 8%
        # until we store per-row OCR marker confidence.
        items = [item.model_copy(update={"tax_rate": 8}) for item in document.items]
    return document.model_copy(
        update={
            "vendor_name": vendor_name,
            "vendor_profile_id": profile.profile_id,
            "layout_profile_name": profile.layout_profile_name,
            "ocr_confidence": confidence,
            "ocr_warnings": warnings,
            "items": items,
        }
    )
