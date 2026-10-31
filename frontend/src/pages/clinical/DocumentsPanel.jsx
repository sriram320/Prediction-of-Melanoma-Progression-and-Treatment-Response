import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, postForm } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import FileDrop from "../../components/FileDrop.jsx";
import { Alert, Badge, Button, EmptyState, Modal, Select, Spinner, TextInput } from "../../components/ui.jsx";
import { categoryLabel, DOCUMENT_CATEGORIES } from "../../utils/clinical.js";
import { downloadFile, formatBytes, openFile } from "../../utils/files.js";
import { errorMessage, formatDate, todayISO } from "../../utils/format.js";
import { useCan } from "./portal.js";

function UploadDocumentModal({ patientId, lesions, onClose, onUploaded }) {
  const can = useCan();
  const [files, setFiles] = useState([]);
  const [form, setForm] = useState({ title: "", category: "lab_report", document_date: "", lesion_id: "", visible: false });
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", files[0]);
      fd.append("title", form.title.trim());
      fd.append("category", form.category);
      if (form.document_date) fd.append("document_date", form.document_date);
      if (form.lesion_id) fd.append("lesion_id", form.lesion_id);
      fd.append("visible_to_patient", form.visible ? "true" : "false");
      return postForm(`/patients/${patientId}/documents`, fd);
    },
    onSuccess: onUploaded,
    onError: (err) => setError(errorMessage(err)),
  });

  const chooseFiles = (list) => {
    setFiles(list);
    if (list[0] && !form.title) setForm((f) => ({ ...f, title: list[0].name.replace(/\.[^.]+$/, "").slice(0, 200) }));
  };

  return (
    <Modal id="upload-document-modal" title="Upload a document" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id="upload-document-cancel">Cancel</Button>
        <Button type="submit" form="upload-document-form" loading={upload.isPending} id="upload-document-submit"
          disabled={!files.length || !form.title.trim()}>Upload</Button>
      </>}>
      <form id="upload-document-form" className="stack" noValidate
        onSubmit={(e) => { e.preventDefault(); setError(""); upload.mutate(); }}>
        <Alert kind="error" id="upload-document-error">{error}</Alert>
        <FileDrop id="upload-document-drop" files={files} onChange={chooseFiles} accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff"
          hint="PDF, JPEG, PNG or TIFF, up to 50 MB" />
        <div className="form-grid">
          <div className="field--full">
            <TextInput id="upload-document-title" label="Title" value={form.title} onChange={set("title")} maxLength={200} required />
          </div>
          <Select id="upload-document-category" label="Category" value={form.category} onChange={set("category")}
            options={DOCUMENT_CATEGORIES} />
          <TextInput id="upload-document-date" label="Document date (optional)" type="date" value={form.document_date}
            onChange={set("document_date")} max={todayISO()} />
          {lesions.length > 0 && (
            <div className="field--full">
              <Select id="upload-document-lesion" label="Related lesion (optional)" value={form.lesion_id}
                onChange={set("lesion_id")}
                options={[{ value: "", label: "Not lesion-specific" }, ...lesions.map((l) => ({ value: l.id, label: l.label }))]} />
            </div>
          )}
        </div>
        {can.shareDocuments ? (
          <label className="checkbox" htmlFor="upload-document-visible">
            <input type="checkbox" id="upload-document-visible" checked={form.visible} onChange={set("visible")} />
            Share with the patient (visible in their portal)
          </label>
        ) : (
          <p className="faint" style={{ fontSize: "0.82rem" }}>
            Documents are uploaded as staff-only. A doctor or hospital admin can share them with the patient.
          </p>
        )}
      </form>
    </Modal>
  );
}

export default function DocumentsPanel({ patientId, lesions }) {
  const can = useCan();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState({ kind: "", text: "" });
  const key = ["patient", patientId, "documents", category];

  const { data, isLoading, isError, error } = useQuery({
    queryKey: key,
    queryFn: () => get(`/patients/${patientId}/documents${category ? `?category=${category}` : ""}`),
  });

  const share = useMutation({
    mutationFn: (doc) => patch(`/documents/${doc.id}`, { visible_to_patient: !doc.visible_to_patient }),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ["patient", patientId, "documents"] });
      setNotice({ kind: "success", text: doc.visible_to_patient ? `"${doc.title}" is now visible to the patient.`
        : `"${doc.title}" is no longer visible to the patient.` });
    },
    onError: (err) => setNotice({ kind: "error", text: errorMessage(err) }),
  });

  const fileAction = async (fn) => {
    setNotice({});
    try { await fn(); } catch (err) { setNotice({ kind: "error", text: errorMessage(err) }); }
  };

  return (
    <div className="stack">
      <div className="row row--between">
        <div style={{ width: 240 }}>
          <label htmlFor="documents-filter" className="visually-hidden">Filter by category</label>
          <select id="documents-filter" className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {DOCUMENT_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <Button id="documents-upload-btn" onClick={() => setUploading(true)}><Icon name="upload" /> Upload document</Button>
      </div>
      <Alert kind={notice.kind || "info"} id="documents-notice">{notice.text}</Alert>

      <div className="card card--flush">
        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 160 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.length === 0 ? (
          <EmptyState icon="document" title={category ? "No documents in this category" : "No documents yet"}>
            <p>Lab reports, histopathology, prescriptions and letters belong here.</p>
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Document</th><th>Category</th><th>Date</th><th>Patient can see</th><th className="table__actions">Actions</th></tr></thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <div className="table__primary">{d.title}</div>
                      <div className="table__secondary">
                        {d.original_filename} · {formatBytes(d.size_bytes)}{d.uploaded_by_name ? ` · by ${d.uploaded_by_name}` : ""}
                      </div>
                    </td>
                    <td>{categoryLabel(d.category)}</td>
                    <td className="faint">{formatDate(d.document_date || d.created_at)}</td>
                    <td>{d.visible_to_patient ? <Badge kind="success" dot>Shared</Badge> : <Badge>Staff only</Badge>}</td>
                    <td className="table__actions">
                      <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                        <Button variant="ghost" size="sm" id={`document-open-${d.id}`}
                          onClick={() => fileAction(() => openFile(d.file_id))}>
                          <Icon name="eye" size={14} /> Open
                        </Button>
                        <Button variant="ghost" size="sm" id={`document-download-${d.id}`}
                          onClick={() => fileAction(() => downloadFile(d.file_id, d.original_filename || d.title))}>
                          Download
                        </Button>
                        {can.shareDocuments && (
                          <Button variant="secondary" size="sm" id={`document-share-${d.id}`}
                            loading={share.isPending && share.variables?.id === d.id} onClick={() => share.mutate(d)}>
                            {d.visible_to_patient ? "Stop sharing" : "Share with patient"}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {uploading && (
        <UploadDocumentModal patientId={patientId} lesions={lesions} onClose={() => setUploading(false)}
          onUploaded={(doc) => {
            queryClient.invalidateQueries({ queryKey: ["patient", patientId] });
            setUploading(false);
            setNotice({ kind: "success", text: `Uploaded "${doc.title}".` });
          }} />
      )}
    </div>
  );
}
