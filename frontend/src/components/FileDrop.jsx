import { useRef, useState } from "react";
import { formatBytes } from "../utils/files.js";
import Icon from "./Icon.jsx";

/** Drag-and-drop or click-to-choose file picker. The server re-checks every file's real type and size. */
export default function FileDrop({ id, files, onChange, multiple = false, accept, hint, maxFiles = 10 }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);

  const add = (list) => {
    const incoming = Array.from(list || []);
    if (!incoming.length) return;
    onChange(multiple ? [...files, ...incoming].slice(0, maxFiles) : incoming.slice(0, 1));
  };

  return (
    <div className="stack stack--sm">
      <div
        className={`dropzone ${over ? "is-over" : ""}`} role="button" tabIndex={0} id={id}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.current?.click())}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
        <Icon name="upload" size={22} />
        <div><strong>Drop {multiple ? "files" : "a file"} here</strong> or click to choose</div>
        {hint && <div className="faint" style={{ fontSize: "0.8rem" }}>{hint}</div>}
        <input ref={input} type="file" hidden multiple={multiple} accept={accept} id={`${id}-input`}
          onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>
      {files.length > 0 && (
        <ul className="file-list" aria-label="Chosen files">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="file-list__item">
              <Icon name="document" size={15} />
              <span className="file-list__name">{f.name}</span>
              <span className="faint">{formatBytes(f.size)}</span>
              <button type="button" className="btn btn--ghost btn--sm" aria-label={`Remove ${f.name}`}
                id={`${id}-remove-${i}`} onClick={() => onChange(files.filter((_, j) => j !== i))}>
                <Icon name="close" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
