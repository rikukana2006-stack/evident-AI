from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.csv_export import matching_result_to_csv
from app.database import Base, engine, get_db
from app.file_types import ALLOWED_FILE_TYPES_LABEL
from app.matching import compare_documents
from app.models import Document, MatchingRun
from app.ocr_service import run_ocr
from app.schemas import (
    DocumentResponse,
    DocumentType,
    DocumentUpdateRequest,
    ExtractedDocument,
    MatchingResult,
    MatchingRunRequest,
)
from app.storage import save_upload
from app.storage import UnsupportedFileTypeError


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///./"):
        db_path = settings.database_url.removeprefix("sqlite:///./")
        db_dir = db_path.rsplit("/", 1)[0] if "/" in db_path else ""
        if db_dir:
            from pathlib import Path

            Path(db_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize_document(document: Document) -> DocumentResponse:
    ocr_data = ExtractedDocument.model_validate(document.ocr_data) if document.ocr_data else None
    return DocumentResponse(
        id=document.id,
        document_type=document.document_type,
        original_filename=document.original_filename,
        status=document.status,
        ocr_data=ocr_data,
    )


def get_document_or_404(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def get_matching_or_404(db: Session, matching_id: str) -> MatchingRun:
    matching = db.get(MatchingRun, matching_id)
    if matching is None:
        raise HTTPException(status_code=404, detail="Matching result not found")
    return matching


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/documents/accepted-file-types")
def accepted_file_types() -> dict[str, str]:
    return {"accepted_file_types": ALLOWED_FILE_TYPES_LABEL}


@app.get("/ocr/status")
def ocr_status() -> dict[str, str | bool | int]:
    return {
        "vision_ocr_provider": settings.vision_ocr_provider,
        "openai_api_key_configured": bool(settings.openai_api_key),
        "openai_vision_model": settings.openai_vision_model,
        "vision_ocr_max_images": settings.vision_ocr_max_images,
        "paddle_ocr_lang": settings.paddle_ocr_lang,
        "paddle_ocr_version": settings.paddle_ocr_version,
        "paddle_cache_dir": str(settings.paddle_cache_dir) if settings.paddle_cache_dir else "",
    }


@app.get("/documents/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)) -> FileResponse:
    document = get_document_or_404(db, document_id)
    path = Path(document.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")
    return FileResponse(path, filename=document.original_filename)


@app.post("/documents/upload", response_model=DocumentResponse)
def upload_document(
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    try:
        original_filename, storage_path = save_upload(file)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    document = Document(
        document_type=document_type,
        original_filename=original_filename,
        storage_path=storage_path,
        status="uploaded",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return serialize_document(document)


@app.post("/documents/{document_id}/ocr", response_model=DocumentResponse)
def run_document_ocr(document_id: str, db: Session = Depends(get_db)) -> DocumentResponse:
    document = get_document_or_404(db, document_id)
    ocr_data = run_ocr(document.document_type, document.original_filename, document.storage_path)
    document.ocr_data = ocr_data.model_dump(mode="json")
    document.status = "ocr_review"
    db.commit()
    db.refresh(document)
    return serialize_document(document)


@app.put("/documents/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: str,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
) -> DocumentResponse:
    document = get_document_or_404(db, document_id)
    document.ocr_data = payload.ocr_data.model_dump(mode="json")
    document.status = "reviewed"
    db.commit()
    db.refresh(document)
    return serialize_document(document)


@app.post("/matching/run", response_model=MatchingResult)
def run_matching(payload: MatchingRunRequest, db: Session = Depends(get_db)) -> MatchingResult:
    delivery_document = get_document_or_404(db, payload.delivery_document_id)
    invoice_document = get_document_or_404(db, payload.invoice_document_id)

    if not delivery_document.ocr_data or not invoice_document.ocr_data:
        raise HTTPException(status_code=400, detail="Both documents must have OCR data before matching")

    result = compare_documents(
        delivery_document_id=delivery_document.id,
        invoice_document_id=invoice_document.id,
        delivery=ExtractedDocument.model_validate(delivery_document.ocr_data),
        invoice=ExtractedDocument.model_validate(invoice_document.ocr_data),
    )
    matching = MatchingRun(
        delivery_document_id=delivery_document.id,
        invoice_document_id=invoice_document.id,
        result=result.model_dump(mode="json"),
        status=result.status,
    )
    db.add(matching)
    db.commit()
    db.refresh(matching)
    result.matching_id = matching.id
    return result


@app.get("/matching/{matching_id}", response_model=MatchingResult)
def get_matching(matching_id: str, db: Session = Depends(get_db)) -> MatchingResult:
    matching = get_matching_or_404(db, matching_id)
    result = MatchingResult.model_validate(matching.result)
    result.matching_id = matching.id
    result.status = matching.status
    return result


def update_matching_status(matching_id: str, status: str, db: Session) -> MatchingResult:
    matching = get_matching_or_404(db, matching_id)
    matching.status = status
    db.commit()
    db.refresh(matching)
    result = MatchingResult.model_validate(matching.result)
    result.matching_id = matching.id
    result.status = matching.status
    return result


@app.post("/matching/{matching_id}/approve", response_model=MatchingResult)
def approve_matching(matching_id: str, db: Session = Depends(get_db)) -> MatchingResult:
    return update_matching_status(matching_id, "approved", db)


@app.post("/matching/{matching_id}/hold", response_model=MatchingResult)
def hold_matching(matching_id: str, db: Session = Depends(get_db)) -> MatchingResult:
    return update_matching_status(matching_id, "held", db)


@app.post("/matching/{matching_id}/reject", response_model=MatchingResult)
def reject_matching(matching_id: str, db: Session = Depends(get_db)) -> MatchingResult:
    return update_matching_status(matching_id, "rejected", db)


@app.get("/matching/{matching_id}/csv")
def export_matching_csv(matching_id: str, db: Session = Depends(get_db)) -> Response:
    matching = get_matching_or_404(db, matching_id)
    # Add a UTF-8 BOM so Japanese text opens correctly in Windows Excel.
    csv_body = "\ufeff" + matching_result_to_csv(matching.result)
    return Response(
        content=csv_body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="matching-{matching_id}.csv"'},
    )
