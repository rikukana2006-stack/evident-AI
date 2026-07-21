"use client";

import {
  Check,
  Download,
  FileCheck2,
  FileUp,
  Hourglass,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Screen = "dashboard" | "upload" | "ocr" | "result";
type DocumentType = "delivery_note" | "invoice";

type DocumentRecord = {
  id: string;
  document_type: DocumentType;
  original_filename: string;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  ocr_data: ExtractedDocument | null;
};

type ExtractedDocument = {
  document_type: DocumentType;
  vendor_name: string;
  document_date: string;
  document_number: string;
  ocr_note?: string | null;
  ocr_provider?: string | null;
  items: Array<{
    item_name: string;
    quantity: number;
    unit_price: number;
    amount: number;
    tax_rate: number;
  }>;
};

type ExtractedItem = ExtractedDocument["items"][number];

type MatchingResult = {
  matching_id: string;
  status: "matched" | "review_required" | "approved" | "held" | "rejected";
  delivery_document_id: string;
  invoice_document_id: string;
  summary: Record<string, number>;
  line_comparisons: Array<{
    delivery_item: ExtractedDocument["items"][number] | null;
    invoice_item: ExtractedDocument["items"][number] | null;
    status: "matched" | "different" | "name_check_required" | "missing_invoice_item" | "missing_delivery_item";
    differences: Array<{
      field: string;
      delivery_value: string | null;
      invoice_value: string | null;
      status: "matched" | "different" | "name_check_required" | "tax_adjusted_match";
    }>;
  }>;
};

type MatchingRunSummary = {
  matching_id: string;
  status: MatchingResult["status"];
  delivery_document_id: string;
  invoice_document_id: string;
  delivery_filename: string | null;
  invoice_filename: string | null;
  summary: Record<string, number>;
  created_at?: string | null;
  updated_at?: string | null;
};

type OcrStatus = {
  vision_ocr_provider: string;
  openai_api_key_configured: boolean;
  openai_vision_model: string;
  vision_ocr_max_images: number;
  paddle_ocr_lang?: string;
  paddle_ocr_version?: string;
  paddle_cache_dir?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const ACCEPTED_DOCUMENT_TYPES = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.heic,.heif,.xlsx,.xls,.csv";
const ACCEPTED_DOCUMENT_TYPES_LABEL = "PDF / 画像 / Excel / CSV";

const statusLabel: Record<string, string> = {
  uploaded: "アップロード済み",
  ocr_review: "OCR確認中",
  reviewed: "確認済み",
  matched: "一致",
  different: "差異あり",
  name_check_required: "品名確認",
  tax_adjusted_match: "税抜/税込換算で一致",
  missing_invoice_item: "請求書に不足",
  missing_delivery_item: "納品書に不足",
  review_required: "確認待ち",
  approved: "承認済み",
  held: "保留",
  rejected: "却下",
};

const fieldLabel: Record<string, string> = {
  item_name: "品名",
  quantity: "数量",
  unit_price: "単価",
  amount: "金額",
  tax_rate: "税率",
  line_item: "明細",
};

const documentTypeLabel: Record<DocumentType, string> = {
  delivery_note: "納品書",
  invoice: "請求書",
};

function formatDifference(field: string, deliveryValue: string | null, invoiceValue: string | null, status?: string) {
  if (status === "tax_adjusted_match") return "税抜/税込換算で一致";
  if (!deliveryValue || !invoiceValue) return "-";
  if (!["quantity", "unit_price", "amount", "tax_rate"].includes(field)) return "-";

  const deliveryNumber = Number(deliveryValue);
  const invoiceNumber = Number(invoiceValue);
  if (Number.isNaN(deliveryNumber) || Number.isNaN(invoiceNumber)) return "-";

  const difference = invoiceNumber - deliveryNumber;
  const sign = difference > 0 ? "+" : "";
  return `${sign}${difference.toLocaleString("ja-JP")}`;
}

function lineTotal(line: MatchingResult["line_comparisons"][number], side: "delivery_item" | "invoice_item") {
  const item = line[side];
  if (!item) return "-";
  return `${item.quantity.toLocaleString("ja-JP")} × ${item.unit_price.toLocaleString("ja-JP")} = ${item.amount.toLocaleString("ja-JP")}`;
}

function parseDocumentJson(value: string): ExtractedDocument | null {
  try {
    return JSON.parse(value) as ExtractedDocument;
  } catch {
    return null;
  }
}

function stringifyDocument(document: ExtractedDocument) {
  return JSON.stringify(document, null, 2);
}

function emptyItem(): ExtractedItem {
  return {
    item_name: "",
    quantity: 0,
    unit_price: 0,
    amount: 0,
    tax_rate: 10,
  };
}

function documentFileUrl(document: DocumentRecord | null) {
  return document ? `${API_BASE}/documents/${document.id}/file` : "";
}

function fileExtension(filename: string) {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [userEmail, setUserEmail] = useState("demo@evident-ai.local");
  const [deliveryFile, setDeliveryFile] = useState<File | null>(null);
  const [invoiceFile, setInvoiceFile] = useState<File | null>(null);
  const [deliveryDocument, setDeliveryDocument] = useState<DocumentRecord | null>(null);
  const [invoiceDocument, setInvoiceDocument] = useState<DocumentRecord | null>(null);
  const [deliveryJson, setDeliveryJson] = useState("");
  const [invoiceJson, setInvoiceJson] = useState("");
  const [matchingResult, setMatchingResult] = useState<MatchingResult | null>(null);
  const [recentDocuments, setRecentDocuments] = useState<DocumentRecord[]>([]);
  const [matchingHistory, setMatchingHistory] = useState<MatchingRunSummary[]>([]);
  const [ocrStatus, setOcrStatus] = useState<OcrStatus | null>(null);
  const [ocrProgress, setOcrProgress] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canMatch = Boolean(deliveryDocument && invoiceDocument && deliveryJson && invoiceJson);
  const reviewedDocumentCount = recentDocuments.filter((document) => document.ocr_data).length;

  const navItems = useMemo(
    () => [
      ["dashboard", "ダッシュボード"],
      ["upload", "書類アップロード"],
      ["ocr", "OCR確認"],
      ["result", "突合結果"],
    ] as const,
    [],
  );

  const request = useCallback(async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, init);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.json();
  }, []);

  const refreshDashboardData = useCallback(async function refreshDashboardData() {
    try {
      const [documents, matchings] = await Promise.all([
        request<DocumentRecord[]>("/documents?limit=12"),
        request<MatchingRunSummary[]>("/matching?limit=8"),
      ]);
      setRecentDocuments(documents);
      setMatchingHistory(matchings);
    } catch {
      // Keep the main workflow usable even if history loading fails.
    }
  }, [request]);

  useEffect(() => {
    try {
      const savedEmail = window.localStorage.getItem("evident-ai-user-email");
      if (savedEmail) setUserEmail(savedEmail);
    } catch {
      setUserEmail("demo@evident-ai.local");
    }
  }, []);

  useEffect(() => {
    refreshDashboardData();
  }, [refreshDashboardData]);

  useEffect(() => {
    if (screen !== "ocr") return;
    fetch(`${API_BASE}/ocr/status`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => setOcrStatus(data as OcrStatus | null))
      .catch(() => setOcrStatus(null));
  }, [screen]);

  function selectDocument(document: DocumentRecord) {
    if (document.document_type === "delivery_note") {
      setDeliveryDocument(document);
      setDeliveryJson(document.ocr_data ? stringifyDocument(document.ocr_data) : "");
    } else {
      setInvoiceDocument(document);
      setInvoiceJson(document.ocr_data ? stringifyDocument(document.ocr_data) : "");
    }
  }

  async function openMatching(matchingId: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await request<MatchingResult>(`/matching/${matchingId}`);
      setMatchingResult(result);
      const documents = recentDocuments.length ? recentDocuments : await request<DocumentRecord[]>("/documents?limit=50");
      const delivery = documents.find((document) => document.id === result.delivery_document_id);
      const invoice = documents.find((document) => document.id === result.invoice_document_id);
      if (delivery) {
        setDeliveryDocument(delivery);
        setDeliveryJson(delivery.ocr_data ? stringifyDocument(delivery.ocr_data) : "");
      }
      if (invoice) {
        setInvoiceDocument(invoice);
        setInvoiceJson(invoice.ocr_data ? stringifyDocument(invoice.ocr_data) : "");
      }
      setScreen("result");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "突合履歴の読み込みに失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  async function uploadOne(documentType: DocumentType, file: File) {
    const form = new FormData();
    form.append("document_type", documentType);
    form.append("file", file);
    return request<DocumentRecord>("/documents/upload", {
      method: "POST",
      body: form,
    });
  }

  async function uploadDocuments() {
    if (!deliveryFile || !invoiceFile) {
      setError("納品書と請求書の両方を選択してください。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [delivery, invoice] = await Promise.all([
        uploadOne("delivery_note", deliveryFile),
        uploadOne("invoice", invoiceFile),
      ]);
      setDeliveryDocument(delivery);
      setInvoiceDocument(invoice);
      refreshDashboardData();
      setScreen("ocr");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "アップロードに失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  async function runOcr() {
    if (!deliveryDocument || !invoiceDocument) return;
    setLoading(true);
    setError(null);
    setOcrProgress("納品書のOCRを実行中です...");
    try {
      // PaddleOCR is CPU-heavy on Windows. Run the two OCR jobs sequentially so
      // the local backend remains responsive and the user can see progress.
      const delivery = await request<DocumentRecord>(`/documents/${deliveryDocument.id}/ocr`, { method: "POST" });
      setDeliveryDocument(delivery);
      setDeliveryJson(JSON.stringify(delivery.ocr_data, null, 2));

      setOcrProgress("請求書のOCRを実行中です...");
      const invoice = await request<DocumentRecord>(`/documents/${invoiceDocument.id}/ocr`, { method: "POST" });
      setInvoiceDocument(invoice);
      setInvoiceJson(JSON.stringify(invoice.ocr_data, null, 2));
      setOcrProgress("OCRが完了しました。抽出された明細を確認してください。");
      refreshDashboardData();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "OCRに失敗しました。");
    } finally {
      setLoading(false);
      setTimeout(() => setOcrProgress(null), 4000);
    }
  }

  async function saveReviewedDocuments() {
    if (!deliveryDocument || !invoiceDocument) return;
    setLoading(true);
    setError(null);
    try {
      const [delivery, invoice] = await Promise.all([
        request<DocumentRecord>(`/documents/${deliveryDocument.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ocr_data: JSON.parse(deliveryJson) }),
        }),
        request<DocumentRecord>(`/documents/${invoiceDocument.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ocr_data: JSON.parse(invoiceJson) }),
        }),
      ]);
      setDeliveryDocument(delivery);
      setInvoiceDocument(invoice);
      refreshDashboardData();
      setScreen("result");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "レビュー保存に失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  async function runMatching() {
    if (!deliveryDocument || !invoiceDocument) return;
    setLoading(true);
    setError(null);
    try {
      const result = await request<MatchingResult>("/matching/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          delivery_document_id: deliveryDocument.id,
          invoice_document_id: invoiceDocument.id,
        }),
      });
      setMatchingResult(result);
      refreshDashboardData();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "突合に失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  async function updateMatchingStatus(action: "approve" | "hold" | "reject") {
    if (!matchingResult) return;
    setLoading(true);
    setError(null);
    try {
      const result = await request<MatchingResult>(`/matching/${matchingResult.matching_id}/${action}`, { method: "POST" });
      setMatchingResult(result);
      refreshDashboardData();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "ステータス更新に失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  function exportCsv() {
    if (!matchingResult) return;
    window.location.href = `${API_BASE}/matching/${matchingResult.matching_id}/csv`;
  }

  return (
    <main className="min-h-screen bg-paper text-ink">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-white px-6 py-4">
        <div>
          <p className="text-sm font-semibold text-teal-700">Evident AI</p>
          <h1 className="text-xl font-bold">Fukkei Match</h1>
        </div>
        <div className="text-sm text-zinc-600">{userEmail}</div>
      </header>

      <div className="grid min-h-[calc(100vh-73px)] grid-cols-[240px_1fr] max-lg:grid-cols-1">
        <nav className="border-r border-line bg-white p-4 max-lg:border-b max-lg:border-r-0">
          <div className="grid gap-2">
            {navItems.map(([id, label]) => (
              <button
                className={`rounded-md px-3 py-2 text-left text-sm font-semibold ${screen === id ? "bg-teal-700 text-white" : "text-zinc-700 hover:bg-zinc-100"}`}
                key={id}
                onClick={() => setScreen(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </nav>

        <section className="p-6">
          {error ? <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

          {screen === "dashboard" ? (
            <div className="grid gap-5">
              <div>
                <h2 className="text-2xl font-bold">ダッシュボード</h2>
                <p className="mt-1 text-sm text-zinc-600">納品書と請求書のアップロードから突合結果の承認まで進めます。</p>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <Metric label="保存済み書類" value={recentDocuments.length} />
                <Metric label="OCR確認済み" value={reviewedDocumentCount} />
                <Metric label="直近の突合" value={matchingResult ? statusLabel[matchingResult.status] : "未実行"} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="inline-flex h-11 w-fit items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white" onClick={() => setScreen("upload")}>
                  <FileUp size={18} />
                  アップロードを開始
                </button>
                <button className="inline-flex h-11 w-fit items-center gap-2 rounded-md border border-line bg-white px-4 font-bold" onClick={refreshDashboardData}>
                  最新の状態に更新
                </button>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <DocumentHistory documents={recentDocuments} selectedDeliveryId={deliveryDocument?.id} selectedInvoiceId={invoiceDocument?.id} onSelect={selectDocument} />
                <MatchingHistory matchings={matchingHistory} onOpen={openMatching} />
              </div>
              {deliveryDocument || invoiceDocument ? (
                <div className="rounded-lg border border-line bg-white p-4">
                  <h3 className="text-sm font-bold text-zinc-700">現在選択中の書類</h3>
                  <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                    <div>
                      <span className="font-bold">納品書: </span>
                      {deliveryDocument?.original_filename ?? "未選択"}
                    </div>
                    <div>
                      <span className="font-bold">請求書: </span>
                      {invoiceDocument?.original_filename ?? "未選択"}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button className="h-10 rounded-md border border-line bg-white px-4 text-sm font-bold disabled:text-zinc-400" disabled={!deliveryDocument || !invoiceDocument} onClick={() => setScreen("ocr")}>
                      OCR確認へ進む
                    </button>
                    <button className="h-10 rounded-md border border-line bg-white px-4 text-sm font-bold disabled:text-zinc-400" disabled={!deliveryDocument || !invoiceDocument} onClick={() => setScreen("result")}>
                      突合結果へ進む
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {screen === "upload" ? (
            <div className="grid gap-5">
              <h2 className="text-2xl font-bold">書類アップロード</h2>
              <p className="text-sm text-zinc-600">対応形式: {ACCEPTED_DOCUMENT_TYPES_LABEL}</p>
              <div className="grid gap-4 lg:grid-cols-2">
                <FilePicker title="納品書" file={deliveryFile} onChange={setDeliveryFile} />
                <FilePicker title="請求書" file={invoiceFile} onChange={setInvoiceFile} />
              </div>
              <button className="inline-flex h-11 w-fit items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={loading} onClick={uploadDocuments}>
                <FileCheck2 size={18} />
                書類をアップロード
              </button>
            </div>
          ) : null}

          {screen === "ocr" ? (
            <div className="grid gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-2xl font-bold">OCR確認</h2>
                <div className="flex gap-2">
                  <button
                    className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold disabled:bg-zinc-100 disabled:text-zinc-500"
                    disabled={loading || !deliveryDocument || !invoiceDocument}
                    onClick={runOcr}
                  >
                    {loading ? <Hourglass size={17} /> : <Play size={17} />}
                    {loading ? "OCR実行中..." : "AI OCRを実行"}
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={loading || !canMatch} onClick={saveReviewedDocuments}>
                    <Check size={17} />
                    確認内容を保存
                  </button>
                </div>
              </div>
              {ocrProgress ? <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-900">{ocrProgress}</div> : null}
              <OcrStatusBanner status={ocrStatus} />
              <div className="grid gap-3 xl:grid-cols-2">
                <OcrNote title="納品書" provider={deliveryDocument?.ocr_data?.ocr_provider} note={deliveryDocument?.ocr_data?.ocr_note} />
                <OcrNote title="請求書" provider={invoiceDocument?.ocr_data?.ocr_provider} note={invoiceDocument?.ocr_data?.ocr_note} />
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <OcrWorkspace title="納品書" document={deliveryDocument} value={deliveryJson} onChange={setDeliveryJson} />
                <OcrWorkspace title="請求書" document={invoiceDocument} value={invoiceJson} onChange={setInvoiceJson} />
              </div>
            </div>
          ) : null}

          {screen === "result" ? (
            <div className="grid gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-2xl font-bold">突合結果</h2>
                <div className="flex flex-wrap gap-2">
                  <button className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold" disabled={loading || !deliveryDocument || !invoiceDocument} onClick={runMatching}>
                    <ShieldCheck size={17} />
                    突合を実行
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-emerald-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("approve")}>
                    <Check size={17} />
                    承認
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-amber-600 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("hold")}>
                    <Hourglass size={17} />
                    保留
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-red-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("reject")}>
                    <X size={17} />
                    却下
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold disabled:text-zinc-400" disabled={!matchingResult} onClick={exportCsv}>
                    <Download size={17} />
                    CSV出力
                  </button>
                </div>
              </div>

              {matchingResult ? (
                <div className="grid gap-4">
                  <div className="grid gap-4 md:grid-cols-5">
                    <Metric label="ステータス" value={statusLabel[matchingResult.status]} />
                    <Metric label="品名確認" value={matchingResult.summary.name_check_required ?? 0} />
                    <Metric label="差異あり" value={matchingResult.summary.different ?? 0} />
                    <Metric label="一致" value={matchingResult.summary.matched ?? 0} />
                    <Metric label="税換算一致" value={matchingResult.summary.tax_adjusted_match ?? 0} />
                  </div>
                  <div className="rounded-lg border border-line bg-white p-4">
                    <h3 className="text-sm font-bold text-zinc-700">確認すべきポイント</h3>
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <Metric label="品名確認" value={matchingResult.summary.name_check_required ?? 0} />
                      <Metric label="数量・単価・金額差異" value={matchingResult.summary.different ?? 0} />
                      <Metric label="不足明細" value={(matchingResult.summary.missing_invoice_item ?? 0) + (matchingResult.summary.missing_delivery_item ?? 0)} />
                      <Metric label="税抜/税込換算一致" value={matchingResult.summary.tax_adjusted_match ?? 0} />
                    </div>
                  </div>
                  <div className="grid gap-3">
                    {matchingResult.line_comparisons.map((line, index) => (
                      <ResultRow key={index} line={line} />
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-line bg-white p-8 text-center text-zinc-600">突合を実行すると、納品書と請求書の差異が表示されます。</div>
              )}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <div className="text-sm font-semibold text-zinc-500">{label}</div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
    </div>
  );
}

function DocumentHistory({
  documents,
  selectedDeliveryId,
  selectedInvoiceId,
  onSelect,
}: {
  documents: DocumentRecord[];
  selectedDeliveryId?: string;
  selectedInvoiceId?: string;
  onSelect: (document: DocumentRecord) => void;
}) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <h3 className="text-sm font-bold text-zinc-700">最近の書類</h3>
      <div className="mt-3 grid gap-2">
        {documents.length ? (
          documents.map((document) => {
            const selected = document.id === selectedDeliveryId || document.id === selectedInvoiceId;
            return (
              <div className="grid gap-2 rounded-md border border-line p-3" key={document.id}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-bold">{document.original_filename}</div>
                    <div className="mt-1 text-xs text-zinc-500">
                      {documentTypeLabel[document.document_type]} / {statusLabel[document.status] ?? document.status} / {formatDateTime(document.created_at)}
                    </div>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-xs font-bold ${selected ? "bg-teal-50 text-teal-700" : "bg-zinc-100 text-zinc-600"}`}>
                    {selected ? "選択中" : document.ocr_data ? "OCR済み" : "未OCR"}
                  </span>
                </div>
                <button className="h-9 w-fit rounded-md border border-line bg-white px-3 text-sm font-bold" type="button" onClick={() => onSelect(document)}>
                  この書類を選択
                </button>
              </div>
            );
          })
        ) : (
          <div className="rounded-md bg-zinc-50 p-4 text-sm text-zinc-600">保存済みの書類はまだありません。</div>
        )}
      </div>
    </section>
  );
}

function MatchingHistory({ matchings, onOpen }: { matchings: MatchingRunSummary[]; onOpen: (matchingId: string) => void }) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <h3 className="text-sm font-bold text-zinc-700">突合履歴</h3>
      <div className="mt-3 grid gap-2">
        {matchings.length ? (
          matchings.map((matching) => (
            <div className="grid gap-2 rounded-md border border-line p-3" key={matching.matching_id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-bold">{statusLabel[matching.status]}</div>
                  <div className="mt-1 text-xs text-zinc-500">{formatDateTime(matching.created_at)}</div>
                </div>
                <div className="text-right text-xs text-zinc-600">
                  差異 {matching.summary.different ?? 0} / 不足 {(matching.summary.missing_invoice_item ?? 0) + (matching.summary.missing_delivery_item ?? 0)}
                </div>
              </div>
              <div className="grid gap-1 text-xs text-zinc-600">
                <div>納品書: {matching.delivery_filename ?? matching.delivery_document_id}</div>
                <div>請求書: {matching.invoice_filename ?? matching.invoice_document_id}</div>
              </div>
              <button className="h-9 w-fit rounded-md border border-line bg-white px-3 text-sm font-bold" type="button" onClick={() => onOpen(matching.matching_id)}>
                結果を開く
              </button>
            </div>
          ))
        ) : (
          <div className="rounded-md bg-zinc-50 p-4 text-sm text-zinc-600">突合履歴はまだありません。</div>
        )}
      </div>
    </section>
  );
}

function FilePicker({ title, file, onChange }: { title: string; file: File | null; onChange: (file: File | null) => void }) {
  return (
    <label className="grid gap-3 rounded-lg border border-line bg-white p-5">
      <span className="text-lg font-bold">{title}</span>
      <input className="rounded-md border border-line p-2" type="file" accept={ACCEPTED_DOCUMENT_TYPES} onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
      <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{ACCEPTED_DOCUMENT_TYPES_LABEL}</span>
      <span className="text-sm text-zinc-600">{file?.name ?? "ファイルが選択されていません"}</span>
    </label>
  );
}

function OcrStatusBanner({ status }: { status: OcrStatus | null }) {
  if (!status) return null;
  const ready = status.vision_ocr_provider === "paddle" || (status.vision_ocr_provider === "openai" && status.openai_api_key_configured);
  const model =
    status.vision_ocr_provider === "paddle"
      ? `${status.paddle_ocr_lang ?? "unknown"} ${status.paddle_ocr_version ?? ""}`.trim()
      : status.openai_vision_model;
  return (
    <div className={`rounded-lg border p-4 text-sm ${ready ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      <div className="font-bold">{ready ? "AI OCRは利用可能です" : "AI OCRは未設定です"}</div>
      <div className="mt-1">
        OCR方式: <span className="font-mono">{status.vision_ocr_provider}</span> / モデル: <span className="font-mono">{model}</span> / APIキー:{" "}
        {status.openai_api_key_configured ? "設定済み" : "未設定"}
        <> / 最大OCRページ数: <span className="font-mono">{status.vision_ocr_max_images}</span></>
        {status.paddle_cache_dir ? <> / キャッシュ: <span className="font-mono">{status.paddle_cache_dir}</span></> : null}
      </div>
    </div>
  );
}

function OcrWorkspace({ title, document, value, onChange }: { title: string; document: DocumentRecord | null; value: string; onChange: (value: string) => void }) {
  return (
    <section className="grid gap-4">
      <DocumentPreview title={title} document={document} />
      <OcrReviewPanel title={title} value={value} onChange={onChange} />
    </section>
  );
}

function DocumentPreview({ title, document }: { title: string; document: DocumentRecord | null }) {
  if (!document) {
    return (
      <section className="rounded-lg border border-line bg-white p-5">
        <h3 className="text-lg font-bold">{title}の原本</h3>
        <div className="mt-3 text-sm text-zinc-500">ファイルはまだアップロードされていません。</div>
      </section>
    );
  }

  const source = documentFileUrl(document);
  const extension = fileExtension(document.original_filename);
  const isImage = ["png", "jpg", "jpeg", "webp", "tif", "tiff", "heic", "heif"].includes(extension);
  const isPdf = extension === "pdf";

  return (
    <section className="grid gap-3 rounded-lg border border-line bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold">{title}の原本</h3>
          <div className="mt-1 text-xs font-semibold text-zinc-500">{document.original_filename}</div>
        </div>
        <a className="rounded-md border border-line px-3 py-2 text-sm font-bold" href={source} target="_blank" rel="noreferrer">
          原本を開く
        </a>
      </div>

      {isPdf ? <iframe className="h-[420px] w-full rounded-md border border-line bg-zinc-50" src={source} title={`${title} PDFプレビュー`} /> : null}
      {isImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="max-h-[420px] w-full rounded-md border border-line object-contain" src={source} alt={`${title}の原本`} />
      ) : null}
      {!isPdf && !isImage ? <div className="rounded-md border border-line bg-zinc-50 p-4 text-sm text-zinc-600">この形式は画面内プレビューに対応していません。「原本を開く」から確認してください。</div> : null}
    </section>
  );
}

function OcrReviewPanel({ title, value, onChange }: { title: string; value: string; onChange: (value: string) => void }) {
  const document = parseDocumentJson(value);

  function updateDocument(updater: (document: ExtractedDocument) => ExtractedDocument) {
    if (!document) return;
    onChange(stringifyDocument(updater(document)));
  }

  function updateField(field: keyof Pick<ExtractedDocument, "vendor_name" | "document_date" | "document_number">, nextValue: string) {
    updateDocument((current) => ({ ...current, [field]: nextValue }));
  }

  function updateItem(index: number, field: keyof ExtractedItem, nextValue: string) {
    updateDocument((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) =>
        itemIndex === index
          ? {
              ...item,
              [field]: field === "item_name" ? nextValue : Number(nextValue || 0),
            }
          : item,
      ),
    }));
  }

  function addItem() {
    updateDocument((current) => ({ ...current, items: [...current.items, emptyItem()] }));
  }

  function removeItem(index: number) {
    updateDocument((current) => ({ ...current, items: current.items.filter((_, itemIndex) => itemIndex !== index) }));
  }

  if (!document) {
    return <JsonEditor title={`${title} JSON`} value={value} onChange={onChange} />;
  }

  return (
    <section className="grid gap-4 rounded-lg border border-line bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold">{title}</h3>
          <div className="mt-1 text-xs font-semibold text-zinc-500">{document.items.length}件の明細</div>
        </div>
        {document.items.length > 0 ? (
          <button className="h-9 rounded-md border border-line bg-white px-3 text-sm font-bold" type="button" onClick={addItem}>
            明細を追加
          </button>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="grid gap-1 text-sm font-semibold">
          取引先
          <input className="h-10 rounded-md border border-line px-3 font-normal" value={document.vendor_name} onChange={(event) => updateField("vendor_name", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-semibold">
          日付
          <input className="h-10 rounded-md border border-line px-3 font-normal" value={document.document_date} onChange={(event) => updateField("document_date", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-semibold">
          書類番号
          <input className="h-10 rounded-md border border-line px-3 font-normal" value={document.document_number} onChange={(event) => updateField("document_number", event.target.value)} />
        </label>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <thead>
            <tr className="border-y border-line text-left text-zinc-500">
              <th className="py-2 pr-2">品名</th>
              <th className="py-2 pr-2">数量</th>
              <th className="py-2 pr-2">単価</th>
              <th className="py-2 pr-2">金額</th>
              <th className="py-2 pr-2">税率</th>
              <th className="py-2 pr-2"></th>
            </tr>
          </thead>
          <tbody>
            {document.items.map((item, index) => (
              <tr className="border-b border-line" key={index}>
                <td className="py-2 pr-2">
                  <input className="h-10 w-full min-w-[220px] rounded-md border border-line px-2" value={item.item_name} onChange={(event) => updateItem(index, "item_name", event.target.value)} />
                </td>
                <td className="py-2 pr-2">
                  <input className="h-10 w-24 rounded-md border border-line px-2" type="number" value={item.quantity} onChange={(event) => updateItem(index, "quantity", event.target.value)} />
                </td>
                <td className="py-2 pr-2">
                  <input className="h-10 w-28 rounded-md border border-line px-2" type="number" value={item.unit_price} onChange={(event) => updateItem(index, "unit_price", event.target.value)} />
                </td>
                <td className="py-2 pr-2">
                  <input className="h-10 w-28 rounded-md border border-line px-2" type="number" value={item.amount} onChange={(event) => updateItem(index, "amount", event.target.value)} />
                </td>
                <td className="py-2 pr-2">
                  <input className="h-10 w-20 rounded-md border border-line px-2" type="number" value={item.tax_rate} onChange={(event) => updateItem(index, "tax_rate", event.target.value)} />
                </td>
                <td className="py-2 pr-2 text-right">
                  <button className="h-9 rounded-md border border-line px-3 text-sm font-bold text-red-700" type="button" onClick={() => removeItem(index)}>
                    削除
                  </button>
                </td>
              </tr>
            ))}
            {document.items.length === 0 ? (
              <tr className="border-b border-line">
                <td className="py-4 text-zinc-500" colSpan={6}>
                  明細を抽出できませんでした。OCR設定と原本を確認し、再度AI OCRを実行してください。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <details>
        <summary className="cursor-pointer text-sm font-bold text-zinc-600">詳細JSON</summary>
        <div className="mt-3">
          <JsonEditor title={`${title} JSON`} value={value} onChange={onChange} framed={false} />
          {document.items.length === 0 ? (
            <button className="mt-3 h-9 rounded-md border border-line bg-white px-3 text-sm font-bold" type="button" onClick={addItem}>
              明細を手動追加
            </button>
          ) : null}
        </div>
      </details>
    </section>
  );
}

function JsonEditor({ title, value, onChange, framed = true }: { title: string; value: string; onChange: (value: string) => void; framed?: boolean }) {
  const className = framed ? "grid gap-3 rounded-lg border border-line bg-white p-5" : "grid gap-3";
  return (
    <label className={className}>
      <span className="text-lg font-bold">{title}</span>
      <textarea className="min-h-[420px] rounded-md border border-line p-3 font-mono text-sm" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function OcrNote({ title, provider, note }: { title: string; provider?: string | null; note?: string | null }) {
  if (!note && !provider) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <div className="font-bold">{title}</div>
      {provider ? <div className="mt-1 font-mono text-xs">{provider}</div> : null}
      {note ? <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-white/70 p-3 font-sans text-xs leading-relaxed">{note}</pre> : null}
    </div>
  );
}

function ResultRow({ line }: { line: MatchingResult["line_comparisons"][number] }) {
  const title = line.delivery_item?.item_name ?? line.invoice_item?.item_name ?? "明細";
  const badgeClass =
    line.status === "matched"
      ? "bg-emerald-50 text-emerald-700"
      : line.status === "name_check_required"
        ? "bg-amber-50 text-amber-700"
        : "bg-red-50 text-red-700";

  return (
    <article className="rounded-lg border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold">{title}</h3>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${badgeClass}`}>{statusLabel[line.status]}</span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-md bg-zinc-50 p-3">
          <div className="text-xs font-bold text-zinc-500">納品書</div>
          <div className="mt-1 text-sm font-semibold">{line.delivery_item?.item_name ?? "-"}</div>
          <div className="mt-1 text-sm text-zinc-600">{lineTotal(line, "delivery_item")}</div>
        </div>
        <div className="rounded-md bg-zinc-50 p-3">
          <div className="text-xs font-bold text-zinc-500">請求書</div>
          <div className="mt-1 text-sm font-semibold">{line.invoice_item?.item_name ?? "-"}</div>
          <div className="mt-1 text-sm text-zinc-600">{lineTotal(line, "invoice_item")}</div>
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-t border-line text-left text-zinc-500">
              <th className="py-2 pr-3">項目</th>
              <th className="py-2 pr-3">納品書</th>
              <th className="py-2 pr-3">請求書</th>
              <th className="py-2 pr-3">差分</th>
              <th className="py-2 pr-3">判定</th>
            </tr>
          </thead>
          <tbody>
            {line.differences.length ? (
              line.differences.map((diff) => (
                <tr className="border-t border-line" key={`${diff.field}-${diff.delivery_value}-${diff.invoice_value}`}>
                  <td className="py-2 pr-3 font-semibold">{fieldLabel[diff.field] ?? diff.field}</td>
                  <td className="py-2 pr-3">{diff.delivery_value ?? "-"}</td>
                  <td className="py-2 pr-3">{diff.invoice_value ?? "-"}</td>
                  <td className="py-2 pr-3 font-semibold">{formatDifference(diff.field, diff.delivery_value, diff.invoice_value, diff.status)}</td>
                  <td className="py-2 pr-3">{statusLabel[diff.status]}</td>
                </tr>
              ))
            ) : (
              <tr className="border-t border-line">
                <td className="py-2 pr-3" colSpan={5}>
                  比較対象の項目はすべて一致しています。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}
