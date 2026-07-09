"use client";

import {
  Check,
  Download,
  FileCheck2,
  FileUp,
  Hourglass,
  LogIn,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

type Screen = "login" | "dashboard" | "upload" | "ocr" | "result";
type DocumentType = "delivery_note" | "invoice";

type DocumentRecord = {
  id: string;
  document_type: DocumentType;
  original_filename: string;
  status: string;
  ocr_data: ExtractedDocument | null;
};

type ExtractedDocument = {
  document_type: DocumentType;
  vendor_name: string;
  document_date: string;
  document_number: string;
  items: Array<{
    item_name: string;
    quantity: number;
    unit_price: number;
    amount: number;
    tax_rate: number;
  }>;
};

type MatchingResult = {
  matching_id: string;
  status: "matched" | "review_required" | "approved" | "held" | "rejected";
  summary: Record<string, number>;
  line_comparisons: Array<{
    delivery_item: ExtractedDocument["items"][number] | null;
    invoice_item: ExtractedDocument["items"][number] | null;
    status: "matched" | "different" | "name_check_required" | "missing_invoice_item" | "missing_delivery_item";
    differences: Array<{
      field: string;
      delivery_value: string | null;
      invoice_value: string | null;
      status: "matched" | "different" | "name_check_required";
    }>;
  }>;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const statusLabel: Record<string, string> = {
  matched: "一致",
  different: "差異あり",
  name_check_required: "品名確認",
  missing_invoice_item: "請求書に不足",
  missing_delivery_item: "納品書に不足",
  review_required: "確認待ち",
  approved: "承認済み",
  held: "保留",
  rejected: "却下",
};

export default function Home() {
  const [screen, setScreen] = useState<Screen>("login");
  const [userEmail, setUserEmail] = useState("demo@evident-ai.local");
  const [password, setPassword] = useState("password");
  const [deliveryFile, setDeliveryFile] = useState<File | null>(null);
  const [invoiceFile, setInvoiceFile] = useState<File | null>(null);
  const [deliveryDocument, setDeliveryDocument] = useState<DocumentRecord | null>(null);
  const [invoiceDocument, setInvoiceDocument] = useState<DocumentRecord | null>(null);
  const [deliveryJson, setDeliveryJson] = useState("");
  const [invoiceJson, setInvoiceJson] = useState("");
  const [matchingResult, setMatchingResult] = useState<MatchingResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canReview = Boolean(deliveryDocument?.ocr_data && invoiceDocument?.ocr_data);
  const canMatch = Boolean(deliveryDocument && invoiceDocument && deliveryJson && invoiceJson);

  const navItems = useMemo(
    () => [
      ["dashboard", "Dashboard"],
      ["upload", "Document Upload"],
      ["ocr", "OCR Review"],
      ["result", "Matching Result"],
    ] as const,
    [],
  );

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, init);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Request failed: ${response.status}`);
    }
    return response.json();
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
    try {
      const [delivery, invoice] = await Promise.all([
        request<DocumentRecord>(`/documents/${deliveryDocument.id}/ocr`, { method: "POST" }),
        request<DocumentRecord>(`/documents/${invoiceDocument.id}/ocr`, { method: "POST" }),
      ]);
      setDeliveryDocument(delivery);
      setInvoiceDocument(invoice);
      setDeliveryJson(JSON.stringify(delivery.ocr_data, null, 2));
      setInvoiceJson(JSON.stringify(invoice.ocr_data, null, 2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "OCRに失敗しました。");
    } finally {
      setLoading(false);
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

  if (screen === "login") {
    return (
      <main className="min-h-screen bg-paper px-6 py-10 text-ink">
        <section className="mx-auto grid max-w-md gap-6 rounded-lg border border-line bg-white p-8 shadow-sm">
          <div>
            <p className="text-sm font-semibold text-teal-700">Evident AI</p>
            <h1 className="mt-2 text-2xl font-bold">Fukkei Match Login</h1>
          </div>
          <label className="grid gap-2 text-sm font-semibold">
            Email
            <input className="rounded-md border border-line px-3 py-2" value={userEmail} onChange={(event) => setUserEmail(event.target.value)} />
          </label>
          <label className="grid gap-2 text-sm font-semibold">
            Password
            <input className="rounded-md border border-line px-3 py-2" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white" onClick={() => setScreen("dashboard")}>
            <LogIn size={18} />
            Login
          </button>
        </section>
      </main>
    );
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
                <h2 className="text-2xl font-bold">Dashboard</h2>
                <p className="mt-1 text-sm text-zinc-600">納品書と請求書のアップロードから突合結果の承認まで進めます。</p>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <Metric label="Uploaded documents" value={(deliveryDocument ? 1 : 0) + (invoiceDocument ? 1 : 0)} />
                <Metric label="OCR reviewed" value={canReview ? 2 : 0} />
                <Metric label="Latest matching" value={matchingResult ? statusLabel[matchingResult.status] : "未実行"} />
              </div>
              <button className="inline-flex h-11 w-fit items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white" onClick={() => setScreen("upload")}>
                <FileUp size={18} />
                Start Upload
              </button>
            </div>
          ) : null}

          {screen === "upload" ? (
            <div className="grid gap-5">
              <h2 className="text-2xl font-bold">Document Upload</h2>
              <div className="grid gap-4 lg:grid-cols-2">
                <FilePicker title="Delivery Note" file={deliveryFile} onChange={setDeliveryFile} />
                <FilePicker title="Invoice" file={invoiceFile} onChange={setInvoiceFile} />
              </div>
              <button className="inline-flex h-11 w-fit items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={loading} onClick={uploadDocuments}>
                <FileCheck2 size={18} />
                Upload Documents
              </button>
            </div>
          ) : null}

          {screen === "ocr" ? (
            <div className="grid gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-2xl font-bold">OCR Review</h2>
                <div className="flex gap-2">
                  <button className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold" disabled={loading || !deliveryDocument || !invoiceDocument} onClick={runOcr}>
                    <Play size={17} />
                    Run Mock OCR
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-teal-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={loading || !canMatch} onClick={saveReviewedDocuments}>
                    <Check size={17} />
                    Save Review
                  </button>
                </div>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <JsonEditor title="Delivery Note JSON" value={deliveryJson} onChange={setDeliveryJson} />
                <JsonEditor title="Invoice JSON" value={invoiceJson} onChange={setInvoiceJson} />
              </div>
            </div>
          ) : null}

          {screen === "result" ? (
            <div className="grid gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-2xl font-bold">Matching Result</h2>
                <div className="flex flex-wrap gap-2">
                  <button className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold" disabled={loading || !deliveryDocument || !invoiceDocument} onClick={runMatching}>
                    <ShieldCheck size={17} />
                    Run Matching
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-emerald-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("approve")}>
                    <Check size={17} />
                    Approve
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-amber-600 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("hold")}>
                    <Hourglass size={17} />
                    Hold
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md bg-red-700 px-4 font-bold text-white disabled:bg-zinc-400" disabled={!matchingResult} onClick={() => updateMatchingStatus("reject")}>
                    <X size={17} />
                    Reject
                  </button>
                  <button className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 font-bold disabled:text-zinc-400" disabled={!matchingResult} onClick={exportCsv}>
                    <Download size={17} />
                    CSV
                  </button>
                </div>
              </div>

              {matchingResult ? (
                <div className="grid gap-4">
                  <div className="grid gap-4 md:grid-cols-4">
                    <Metric label="Status" value={statusLabel[matchingResult.status]} />
                    <Metric label="Name check" value={matchingResult.summary.name_check_required ?? 0} />
                    <Metric label="Different" value={matchingResult.summary.different ?? 0} />
                    <Metric label="Matched" value={matchingResult.summary.matched ?? 0} />
                  </div>
                  <div className="grid gap-3">
                    {matchingResult.line_comparisons.map((line, index) => (
                      <ResultRow key={index} line={line} />
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-line bg-white p-8 text-center text-zinc-600">Run Matching to see differences for milk and bread.</div>
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

function FilePicker({ title, file, onChange }: { title: string; file: File | null; onChange: (file: File | null) => void }) {
  return (
    <label className="grid gap-3 rounded-lg border border-line bg-white p-5">
      <span className="text-lg font-bold">{title}</span>
      <input className="rounded-md border border-line p-2" type="file" onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
      <span className="text-sm text-zinc-600">{file?.name ?? "No file selected"}</span>
    </label>
  );
}

function JsonEditor({ title, value, onChange }: { title: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-3 rounded-lg border border-line bg-white p-5">
      <span className="text-lg font-bold">{title}</span>
      <textarea className="min-h-[420px] rounded-md border border-line p-3 font-mono text-sm" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function ResultRow({ line }: { line: MatchingResult["line_comparisons"][number] }) {
  const title = line.delivery_item?.item_name ?? line.invoice_item?.item_name ?? "Line item";
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
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-t border-line text-left text-zinc-500">
              <th className="py-2 pr-3">Field</th>
              <th className="py-2 pr-3">Delivery Note</th>
              <th className="py-2 pr-3">Invoice</th>
              <th className="py-2 pr-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {line.differences.length ? (
              line.differences.map((diff) => (
                <tr className="border-t border-line" key={`${diff.field}-${diff.delivery_value}-${diff.invoice_value}`}>
                  <td className="py-2 pr-3 font-semibold">{diff.field}</td>
                  <td className="py-2 pr-3">{diff.delivery_value ?? "-"}</td>
                  <td className="py-2 pr-3">{diff.invoice_value ?? "-"}</td>
                  <td className="py-2 pr-3">{statusLabel[diff.status]}</td>
                </tr>
              ))
            ) : (
              <tr className="border-t border-line">
                <td className="py-2 pr-3" colSpan={4}>
                  All compared fields match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}
