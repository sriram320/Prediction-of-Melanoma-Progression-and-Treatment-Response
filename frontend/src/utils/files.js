// Protected files are fetched with the access token and shown through in-memory blob: URLs.
// Thumbnails are cached for the session (and dropped on sign-out); full-size images are fetched per view.
import { getBlob } from "../api/client.js";

const thumbCache = new Map(); // "fileId:size" -> Promise<objectURL>

export function thumbnailUrl(fileId, size = 256) {
  const key = `${fileId}:${size}`;
  if (!thumbCache.has(key)) {
    const promise = getBlob(`/files/${fileId}/thumbnail?size=${size}`).then((blob) => URL.createObjectURL(blob));
    promise.catch(() => thumbCache.delete(key));
    thumbCache.set(key, promise);
  }
  return thumbCache.get(key);
}

export function clearFileCache() {
  for (const promise of thumbCache.values()) promise.then((url) => URL.revokeObjectURL(url), () => {});
  thumbCache.clear();
}

/** Opens a file in a new tab. The tab is opened synchronously so pop-up blockers allow it. */
export async function openFile(fileId) {
  const tab = window.open("", "_blank");
  try {
    const url = URL.createObjectURL(await getBlob(`/files/${fileId}/content`));
    if (tab) tab.location.href = url;
    else window.location.assign(url);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    tab?.close();
    throw err;
  }
}

export async function downloadFile(fileId, filename) {
  const url = URL.createObjectURL(await getBlob(`/files/${fileId}/content?download=true`));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "file";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function formatBytes(n) {
  if (!n && n !== 0) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
