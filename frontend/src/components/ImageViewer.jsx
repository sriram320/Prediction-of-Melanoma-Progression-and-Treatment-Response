import { useRef, useState } from "react";
import SecureImage from "./SecureImage.jsx";
import { Modal } from "./ui.jsx";

const ZOOMS = [1, 1.5, 2, 3];

/**
 * Full-size viewer for one image, or two side by side for comparing visits.
 * `items`: [{fileId, caption}]. In compare mode zoom and scrolling are linked so both panes show the same region.
 */
export default function ImageViewer({ id, title, items, onClose, controls }) {
  const [zoom, setZoom] = useState(1);
  const panes = useRef([]);
  const syncing = useRef(false);

  const onScroll = (index) => {
    if (syncing.current || items.length < 2) return;
    const src = panes.current[index];
    const dst = panes.current[1 - index];
    if (!src || !dst) return;
    syncing.current = true;
    const fx = src.scrollLeft / Math.max(1, src.scrollWidth - src.clientWidth);
    const fy = src.scrollTop / Math.max(1, src.scrollHeight - src.clientHeight);
    dst.scrollLeft = fx * (dst.scrollWidth - dst.clientWidth);
    dst.scrollTop = fy * (dst.scrollHeight - dst.clientHeight);
    requestAnimationFrame(() => { syncing.current = false; });
  };

  return (
    <Modal id={id} title={title} onClose={onClose} wide>
      {controls}
      <div className="row row--between" style={{ marginBottom: 12 }}>
        <span className="faint" style={{ fontSize: "0.85rem" }}>
          {items.length > 1 ? "Zoom and scrolling are linked between the two images." : "Use zoom to inspect detail."}
        </span>
        <div className="segmented" role="group" aria-label="Zoom">
          {ZOOMS.map((z) => (
            <button key={z} type="button" className="segmented__btn" aria-pressed={zoom === z}
              id={`${id}-zoom-${String(z).replace(".", "_")}`} onClick={() => setZoom(z)}>
              {z === 1 ? "Fit" : `${z}x`}
            </button>
          ))}
        </div>
      </div>
      <div className={`viewer ${items.length > 1 ? "viewer--compare" : ""}`}>
        {items.map((item, i) => (
          <figure key={`${i}-${item.fileId}`} className="viewer__figure">
            <figcaption className="viewer__caption">{item.caption}</figcaption>
            <div className="viewer__pane" ref={(el) => { panes.current[i] = el; }} onScroll={() => onScroll(i)}>
              <SecureImage fileId={item.fileId} full alt={item.caption} className="viewer__img"
                style={{ width: `${zoom * 100}%` }} />
            </div>
          </figure>
        ))}
      </div>
    </Modal>
  );
}
