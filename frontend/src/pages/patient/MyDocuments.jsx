import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { Alert, Button, EmptyState, PageHeader } from "../../components/ui.jsx";
import { categoryLabel } from "../../utils/clinical.js";
import { downloadFile, formatBytes, openFile } from "../../utils/files.js";
import { errorMessage, formatDate } from "../../utils/format.js";

const EXT = { "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png" };

export default function MyDocuments() {
  const [error, setError] = useState("");
  const { data, isLoading, isError, error: loadError } = useQuery({
    queryKey: ["me", "documents"], queryFn: () => get("/me/documents"),
  });
  const run = async (fn) => {
    setError("");
    try { await fn(); } catch (err) { setError(errorMessage(err)); }
  };

  if (isLoading) return <PageLoading />;
  return (
    <>
      <PageHeader eyebrow="Your record" title="Documents"
        subtitle="Documents your hospital has shared with you, such as lab results and letters." />
      <div className="stack">
        <Alert kind="error" id="my-documents-error">{error}</Alert>
        {isError ? <Alert kind="error">{errorMessage(loadError)}</Alert> : data.length === 0 ? (
          <div className="card"><EmptyState icon="document" title="No documents shared yet">
            <p>When your doctor shares a document with you, it will appear here.</p>
          </EmptyState></div>
        ) : (
          <div className="card card--flush">
            <ul className="doc-list">
              {data.map((d) => (
                <li key={d.id} className="doc-list__item">
                  <div className="doc-list__icon"><Icon name="document" size={20} /></div>
                  <div className="doc-list__body">
                    <div className="table__primary">{d.title}</div>
                    <div className="table__secondary">
                      {categoryLabel(d.category)} · {formatDate(d.document_date || d.created_at)} · {formatBytes(d.size_bytes)}
                    </div>
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <Button variant="secondary" size="sm" id={`my-document-open-${d.id}`} onClick={() => run(() => openFile(d.file_id))}>
                      <Icon name="eye" size={14} /> Open
                    </Button>
                    <Button variant="ghost" size="sm" id={`my-document-download-${d.id}`}
                      onClick={() => run(() => downloadFile(d.file_id, `${d.title}.${EXT[d.mime_type] || "bin"}`))}>
                      Download
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </>
  );
}
