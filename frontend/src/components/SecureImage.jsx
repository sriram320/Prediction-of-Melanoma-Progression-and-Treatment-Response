import { useEffect, useState } from "react";
import { getBlob } from "../api/client.js";
import { thumbnailUrl } from "../utils/files.js";
import Icon from "./Icon.jsx";

/** Shows a protected image: a cached thumbnail by default, or the full file when `full` is set. */
export default function SecureImage({ fileId, size = 256, full = false, alt, className, style }) {
  const [state, setState] = useState({ url: null, failed: false });

  useEffect(() => {
    if (!fileId) return undefined;
    let alive = true;
    let ownUrl = null;
    setState({ url: null, failed: false });
    const load = full
      ? getBlob(`/files/${fileId}/content`).then((blob) => {
        ownUrl = URL.createObjectURL(blob);
        return ownUrl;
      })
      : thumbnailUrl(fileId, size);
    load.then((url) => alive && setState({ url, failed: false }))
      .catch(() => alive && setState({ url: null, failed: true }));
    return () => {
      alive = false;
      if (full) load.then((url) => URL.revokeObjectURL(url), () => {});
    };
  }, [fileId, size, full]);

  if (state.failed) {
    return (
      <div className={`image-fallback ${className || ""}`} style={style} role="img" aria-label={`${alt} (could not load)`}>
        <Icon name="alert" size={20} />
      </div>
    );
  }
  if (!state.url) return <div className={`skeleton ${className || ""}`} style={style} aria-busy="true" aria-label={alt} />;
  return <img src={state.url} alt={alt} className={className} style={style} draggable={false} />;
}
