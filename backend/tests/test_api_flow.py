from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    previous_storage_dir = settings.storage_dir
    settings.storage_dir = tmp_path / "storage"

    def override_get_db() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    settings.storage_dir = previous_storage_dir


def upload_csv(client: TestClient, document_type: str, filename: str, csv_text: str) -> dict:
    response = client.post(
        "/documents/upload",
        data={"document_type": document_type},
        files={"file": (filename, csv_text.encode("utf-8-sig"), "text/csv")},
    )
    assert response.status_code == 200
    return response.json()


def test_api_flow_from_csv_upload_to_csv_export(client: TestClient) -> None:
    delivery_csv = (
        "item_name,quantity,unit_price,amount,tax_rate\n"
        "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73,20,100,2000,8\n"
        "\u30d1\u30f3,30,80,2400,8\n"
    )
    invoice_csv = (
        "item_name,quantity,unit_price,amount,tax_rate\n"
        "\u304a\u3044\u3057\u3044\u725b\u4e73,18,100,1800,8\n"
        "\u30d1\u30f3,30,90,2700,8\n"
    )

    assert client.get("/health").json() == {"status": "ok"}
    ocr_status = client.get("/ocr/status")
    assert ocr_status.status_code == 200
    assert "openai_api_key_configured" in ocr_status.json()

    delivery = upload_csv(client, "delivery_note", "delivery.csv", delivery_csv)
    invoice = upload_csv(client, "invoice", "invoice.csv", invoice_csv)

    delivery_file = client.get(f"/documents/{delivery['id']}/file")
    assert delivery_file.status_code == 200
    assert delivery_file.content.startswith(b"\xef\xbb\xbfitem_name")

    delivery_ocr = client.post(f"/documents/{delivery['id']}/ocr")
    invoice_ocr = client.post(f"/documents/{invoice['id']}/ocr")
    assert delivery_ocr.status_code == 200
    assert invoice_ocr.status_code == 200
    assert delivery_ocr.json()["ocr_data"]["items"][0]["item_name"] == "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73"

    delivery_review = client.put(
        f"/documents/{delivery['id']}",
        json={"ocr_data": delivery_ocr.json()["ocr_data"]},
    )
    invoice_review = client.put(
        f"/documents/{invoice['id']}",
        json={"ocr_data": invoice_ocr.json()["ocr_data"]},
    )
    assert delivery_review.json()["status"] == "reviewed"
    assert invoice_review.json()["status"] == "reviewed"

    matching = client.post(
        "/matching/run",
        json={"delivery_document_id": delivery["id"], "invoice_document_id": invoice["id"]},
    )
    assert matching.status_code == 200
    matching_body = matching.json()
    assert matching_body["status"] == "review_required"
    assert matching_body["summary"]["name_check_required"] == 1
    assert matching_body["summary"]["different"] == 1

    matching_id = matching_body["matching_id"]
    assert client.post(f"/matching/{matching_id}/hold").json()["status"] == "held"
    assert client.post(f"/matching/{matching_id}/approve").json()["status"] == "approved"
    assert client.post(f"/matching/{matching_id}/reject").json()["status"] == "rejected"

    csv_response = client.get(f"/matching/{matching_id}/csv")
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert "品名" in csv_response.text
    assert "単価" in csv_response.text


def test_api_rejects_unsupported_upload(client: TestClient) -> None:
    response = client.post(
        "/documents/upload",
        data={"document_type": "delivery_note"},
        files={"file": ("note.txt", b"demo", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]
