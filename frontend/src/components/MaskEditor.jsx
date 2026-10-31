import { useEffect, useRef, useState } from "react";
import { getBlob } from "../api/client.js";
import { Alert, Button, Modal, Spinner } from "./ui.jsx";

const PAINT = "rgb(23, 195, 217)";

function loadImage(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => resolve({ img, url });
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Image could not be decoded")); };
    img.src = url;
  });
}

/**
 * Shows a scan with its lesion outline. Doctors can confirm the outline, or paint/erase a corrected one; it is
 * saved as a black-and-white PNG the size of the scan. `canEdit=false` gives a view-only overlay.
 */
export default function MaskEditor({ image, caption, canEdit, onSubmit, onClose }) {
  const canvas = useRef(null);
  const drawing = useRef(null);
  const [scanUrl, setScanUrl] = useState(null);
  const [aiMask, setAiMask] = useState(null);
  const [tool, setTool] = useState("paint");
  const [brush, setBrush] = useState(24);
  const [changed, setChanged] = useState(false);
  const [showOutline, setShowOutline] = useState(true);
  const [state, setState] = useState({ loading: true, error: "", saving: false });

  const paintMask = (maskImg) => {
    const c = canvas.current;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    if (!maskImg) return;
    const tmp = document.createElement("canvas");
    tmp.width = c.width;
    tmp.height = c.height;
    const t = tmp.getContext("2d");
    t.drawImage(maskImg, 0, 0, c.width, c.height);
    const src = t.getImageData(0, 0, c.width, c.height);
    const out = ctx.createImageData(c.width, c.height);
    for (let i = 0; i < src.data.length; i += 4) {
      if (src.data[i] > 127) {
        out.data[i] = 23; out.data[i + 1] = 195; out.data[i + 2] = 217; out.data[i + 3] = 255;
      }
    }
    ctx.putImageData(out, 0, 0);
  };

  useEffect(() => {
    let alive = true;
    const urls = [];
    (async () => {
      try {
        const scan = await loadImage(await getBlob(`/files/${image.file_id}/content`));
        urls.push(scan.url);
        let mask = null;
        if (image.mask_file_id) {
          mask = await loadImage(await getBlob(`/files/${image.mask_file_id}/content`));
          urls.push(mask.url);
        }
        if (!alive) return;
        canvas.current.width = scan.img.naturalWidth;
        canvas.current.height = scan.img.naturalHeight;
        setScanUrl(scan.url);
        setAiMask(mask?.img || null);
        paintMask(mask?.img || null);
        setState({ loading: false, error: "", saving: false });
      } catch (err) {
        if (alive) setState({ loading: false, error: err.message || "Could not load the scan", saving: false });
      }
    })();
    return () => {
      alive = false;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [image.file_id, image.mask_file_id]);

  const point = (e) => {
    const r = canvas.current.getBoundingClientRect();
    return [(e.clientX - r.left) * (canvas.current.width / r.width), (e.clientY - r.top) * (canvas.current.height / r.height)];
  };
  const scale = () => canvas.current.width / canvas.current.getBoundingClientRect().width;

  const stroke = (from, to) => {
    const ctx = canvas.current.getContext("2d");
    ctx.globalCompositeOperation = tool === "erase" ? "destination-out" : "source-over";
    ctx.strokeStyle = PAINT;
    ctx.fillStyle = PAINT;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = brush * scale();
    ctx.beginPath();
    ctx.moveTo(...from);
    ctx.lineTo(...to);
    ctx.stroke();
    ctx.globalCompositeOperation = "source-over";
  };

  const onDown = (e) => {
    if (!canEdit || state.loading) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = point(e);
    drawing.current = p;
    stroke(p, p);
    setChanged(true);
  };
  const onMove = (e) => {
    if (!drawing.current) return;
    const p = point(e);
    stroke(drawing.current, p);
    drawing.current = p;
  };
  const onUp = () => { drawing.current = null; };

  const exportPng = () => new Promise((resolve) => {
    const c = canvas.current;
    const src = c.getContext("2d").getImageData(0, 0, c.width, c.height);
    const out = new ImageData(c.width, c.height);
    for (let i = 0; i < src.data.length; i += 4) {
      const v = src.data[i + 3] > 0 ? 255 : 0;
      out.data[i] = v; out.data[i + 1] = v; out.data[i + 2] = v; out.data[i + 3] = 255;
    }
    const tmp = document.createElement("canvas");
    tmp.width = c.width;
    tmp.height = c.height;
    tmp.getContext("2d").putImageData(out, 0, 0);
    tmp.toBlob(resolve, "image/png");
  });

  const submit = async (kind) => {
    setState((s) => ({ ...s, saving: true, error: "" }));
    try {
      const fd = new FormData();
      if (kind === "confirm") fd.append("confirm", "true");
      else fd.append("file", await exportPng(), "outline.png");
      await onSubmit(fd);
    } catch (err) {
      setState((s) => ({ ...s, saving: false, error: err.detail || err.message }));
    }
  };

  return (
    <Modal id="mask-editor" title={canEdit ? "Review the lesion outline" : "Lesion outline"} onClose={onClose} wide
      footer={canEdit && (
        <>
          <Button variant="secondary" id="mask-editor-cancel" onClick={onClose}>Cancel</Button>
          {image.mask_file_id && !changed && (
            <Button variant="secondary" id="mask-editor-confirm" loading={state.saving} onClick={() => submit("confirm")}>
              Outline is correct
            </Button>
          )}
          <Button id="mask-editor-save" disabled={!changed} loading={state.saving} onClick={() => submit("save")}>
            Save corrected outline
          </Button>
        </>
      )}>
      <div className="stack stack--sm">
        <div className="row row--between">
          <span className="faint" style={{ fontSize: "0.85rem" }}>
            {caption}
            {image.mask_confirmed ? " · confirmed by a doctor"
              : image.mask_confidence != null ? ` · AI outline confidence ${Math.round(image.mask_confidence * 100)}%` : " · no outline yet"}
          </span>
          <div className="row" style={{ gap: 8 }}>
            <label className="checkbox" htmlFor="mask-editor-show">
              <input type="checkbox" id="mask-editor-show" checked={showOutline} onChange={(e) => setShowOutline(e.target.checked)} />
              Show outline
            </label>
            {canEdit && (
              <>
                <div className="segmented" role="group" aria-label="Brush tool">
                  {["paint", "erase"].map((t) => (
                    <button key={t} type="button" className="segmented__btn" aria-pressed={tool === t}
                      id={`mask-editor-${t}`} onClick={() => setTool(t)}>{t === "paint" ? "Paint" : "Erase"}</button>
                  ))}
                </div>
                <label className="row faint" htmlFor="mask-editor-brush" style={{ gap: 6, fontSize: "0.82rem" }}>
                  Brush
                  <input id="mask-editor-brush" type="range" min="4" max="80" value={brush}
                    onChange={(e) => setBrush(Number(e.target.value))} />
                </label>
                <Button variant="ghost" size="sm" id="mask-editor-reset" disabled={!changed}
                  onClick={() => { paintMask(aiMask); setChanged(false); }}>Reset</Button>
                <Button variant="ghost" size="sm" id="mask-editor-clear"
                  onClick={() => { paintMask(null); setChanged(true); }}>Clear</Button>
              </>
            )}
          </div>
        </div>
        <Alert kind="error" id="mask-editor-error">{state.error}</Alert>
        <div className="mask-editor">
          {state.loading && <div className="mask-editor__loading"><Spinner /></div>}
          {scanUrl && <img src={scanUrl} alt={caption} className="mask-editor__scan" draggable={false} />}
          <canvas ref={canvas} className={`mask-editor__canvas ${canEdit ? "is-editable" : ""}`}
            style={{ opacity: showOutline ? 0.45 : 0 }}
            onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
            aria-label={canEdit ? "Outline drawing area: drag to paint or erase" : "Lesion outline overlay"} />
        </div>
        {canEdit && (
          <p className="faint" style={{ fontSize: "0.82rem" }}>
            A confirmed or corrected outline is kept when the analysis is run again, and a low outline confidence no
            longer forces a referral. Run the analysis again after correcting it.
          </p>
        )}
      </div>
    </Modal>
  );
}
