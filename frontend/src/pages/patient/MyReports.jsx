import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { Alert, Button, EmptyState, PageHeader } from "../../components/ui.jsx";
import { PATIENT_CATEGORY, siteLabel } from "../../utils/clinical.js";
import { downloadPath, openPath } from "../../utils/files.js";
import { errorMessage, formatDate } from "../../utils/format.js";

/** Released reports only, in the doctor's words. */
export default function MyReports() {
  const [error, setError] = useState("");
  const { data, isLoading, isError, error: loadError } = useQuery({ queryKey: ["me", "reports"], queryFn: () => get("/me/reports") });
  const run = async (fn) => {
    setError("");
    try { await fn(); } catch (err) { setError(errorMessage(err)); }
  };

  if (isLoading) return <PageLoading />;
  return (
    <>
      <PageHeader eyebrow="Your record" title="Reports"
        subtitle="Reports your doctor has reviewed, signed and shared with you." />
      <div className="stack">
        <Alert kind="error" id="my-reports-error">{error}</Alert>
        {isError ? <Alert kind="error">{errorMessage(loadError)}</Alert> : data.length === 0 ? (
          <div className="card"><EmptyState icon="report" title="No reports yet">
            <p>When your doctor has reviewed your photos and signed a report, it will appear here.</p>
          </EmptyState></div>
        ) : data.map((r) => {
          const cat = PATIENT_CATEGORY[r.final_category];
          return (
            <article key={r.id} className="card my-report" aria-labelledby={`my-report-${r.id}`}>
              <div className="card__header">
                <div>
                  <h2 id={`my-report-${r.id}`} className="card__title">
                    {r.lesion_label ? `${r.lesion_label} · ${siteLabel(r.anatomical_site)}` : "Skin check report"}
                  </h2>
                  <div className="faint" style={{ fontSize: "0.82rem" }}>
                    Report {r.report_number}{r.version > 1 ? " (updated)" : ""} · shared {formatDate(r.released_at)}
                  </div>
                </div>
              </div>
              <div className={`verdict verdict--${cat.tone}`}>
                <Icon name={cat.icon} size={22} />
                <div className="verdict__title">{cat.label}</div>
              </div>
              {r.patient_summary && <p style={{ marginTop: 14, whiteSpace: "pre-wrap" }}>{r.patient_summary}</p>}
              {r.recommendation && (
                <p style={{ marginTop: 10 }}><strong>What to do next:</strong> {r.recommendation}</p>
              )}
              <div className="row row--between" style={{ marginTop: 16 }}>
                <span className="faint" style={{ fontSize: "0.85rem" }}>Signed by {r.signed_by_name} on {formatDate(r.signed_at)}</span>
                <div className="row" style={{ gap: 6 }}>
                  <Button variant="secondary" size="sm" id={`my-report-open-${r.id}`}
                    onClick={() => run(() => openPath(`/reports/${r.id}/pdf`))}>
                    <Icon name="eye" size={14} /> Open PDF
                  </Button>
                  <Button variant="ghost" size="sm" id={`my-report-download-${r.id}`}
                    onClick={() => run(() => downloadPath(`/reports/${r.id}/pdf?download=true`, `${r.report_number}.pdf`))}>
                    Download
                  </Button>
                </div>
              </div>
            </article>
          );
        })}
        <p className="faint" style={{ fontSize: "0.85rem" }}>
          Questions about a report? Please contact your hospital. These reports support your doctor's assessment; they are
          not a diagnosis on their own.
        </p>
      </div>
    </>
  );
}
