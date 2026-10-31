import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import ImageViewer from "../../components/ImageViewer.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import SecureImage from "../../components/SecureImage.jsx";
import { Alert, Button, EmptyState, PageHeader } from "../../components/ui.jsx";
import { siteLabel } from "../../utils/clinical.js";
import { errorMessage, formatDate } from "../../utils/format.js";

const firstImage = (visit) => visit.images.find((i) => i.modality === "dermoscopic") || visit.images[0];

function LesionCard({ lesion, onView }) {
  const withPhotos = lesion.visits.filter((v) => v.images.length);
  const first = withPhotos[0];
  const last = withPhotos[withPhotos.length - 1];
  return (
    <section className="card" aria-labelledby={`my-lesion-${lesion.id}`}>
      <div className="card__header">
        <div>
          <h2 id={`my-lesion-${lesion.id}`} className="card__title">{lesion.label}</h2>
          <div className="faint" style={{ fontSize: "0.85rem" }}>
            {siteLabel(lesion.anatomical_site)} · {lesion.visits.length} visit{lesion.visits.length === 1 ? "" : "s"}
          </div>
        </div>
        {withPhotos.length > 1 && (
          <Button variant="secondary" size="sm" id={`my-lesion-${lesion.id}-compare`}
            onClick={() => onView(lesion.label, [
              { fileId: firstImage(first).file_id, caption: `First photo · ${formatDate(first.visit_date)}` },
              { fileId: firstImage(last).file_id, caption: `Latest photo · ${formatDate(last.visit_date)}` },
            ])}>
            Compare first and latest
          </Button>
        )}
      </div>
      {withPhotos.length === 0 ? (
        <p className="muted">No photos yet for this spot.</p>
      ) : (
        <div className="visit-strip">
          {withPhotos.map((v) => (
            <button key={v.id} type="button" className="visit-strip__item" id={`my-visit-${v.id}`}
              onClick={() => onView(lesion.label, [{ fileId: firstImage(v).file_id, caption: formatDate(v.visit_date) }])}
              aria-label={`View the photo from ${formatDate(v.visit_date)}`}>
              <span className="thumb"><SecureImage fileId={firstImage(v).file_id} alt="" /></span>
              <span className="visit-strip__date">{formatDate(v.visit_date)}</span>
            </button>
          ))}
        </div>
      )}
      {withPhotos.length === 1 && (
        <p className="faint" style={{ fontSize: "0.85rem", marginTop: 12 }}>
          This is the first photo of this spot. At later visits your doctor compares new photos with it to see whether
          anything has changed.
        </p>
      )}
    </section>
  );
}

export default function MyScans() {
  const [viewer, setViewer] = useState(null);
  const { data, isLoading, isError, error } = useQuery({ queryKey: ["me", "lesions"], queryFn: () => get("/me/lesions") });

  if (isLoading) return <PageLoading />;
  return (
    <>
      <PageHeader eyebrow="Your record" title="My scans"
        subtitle="Photos of each spot your hospital is keeping an eye on, by visit date. Your doctor reviews how they change over time." />
      {isError ? <Alert kind="error">{errorMessage(error)}</Alert> : data.length === 0 ? (
        <div className="card"><EmptyState icon="lesion" title="No scans yet">
          <p>Photos taken at your hospital visits will appear here.</p>
        </EmptyState></div>
      ) : (
        <div className="stack stack--lg">
          {data.map((l) => <LesionCard key={l.id} lesion={l} onView={(title, items) => setViewer({ title, items })} />)}
        </div>
      )}
      {viewer && <ImageViewer id="my-scan-viewer" title={viewer.title} items={viewer.items} onClose={() => setViewer(null)} />}
    </>
  );
}
