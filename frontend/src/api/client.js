// Fetch wrapper for /api/v1.
// The access token lives only in memory (never localStorage). The refresh token is an httpOnly cookie
// scoped to /api/v1/auth, so a 401 triggers one silent refresh and a single retry.

const BASE = "/api/v1";

let accessToken = null;
let refreshInFlight = null;
let sessionEndHandler = () => {};

export class ApiError extends Error {
  constructor(status, code, detail, errors) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.errors = errors || [];
  }
}

export function setAccessToken(token) {
  accessToken = token;
}

export function onSessionEnd(handler) {
  sessionEndHandler = handler;
}

async function parse(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!res.ok) {
    throw new ApiError(res.status, body?.code || "ERROR", body?.detail || res.statusText, body?.errors);
  }
  return body;
}

async function send(path, { method = "GET", body, headers = {} } = {}) {
  const h = { Accept: "application/json", ...headers };
  if (accessToken) h.Authorization = `Bearer ${accessToken}`;
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    h["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  try {
    return await fetch(`${BASE}${path}`, { method, headers: h, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check your connection and try again.");
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Rotates the refresh cookie and returns {access_token, user}. Concurrent callers share one request. */
export function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" });
        try {
          const data = await parse(res);
          setAccessToken(data.access_token);
          return data;
        } catch (err) {
          // Another tab refreshed at the same moment; the browser now holds the new cookie, so retry once.
          if (err.code === "REFRESH_RACE" && attempt === 0) {
            await sleep(300);
            continue;
          }
          setAccessToken(null);
          throw err;
        }
      }
      throw new ApiError(401, "NO_SESSION", "Not signed in");
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

const NO_RETRY = ["/auth/refresh", "/auth/logout", "/auth/hospital/login", "/auth/patient/login",
  "/auth/admin/login", "/auth/patient/activate"];

/** Sends with one silent refresh-and-retry on 401; returns the raw Response. */
async function request(path, options = {}) {
  let res = await send(path, options);
  if (res.status === 401 && accessToken && !NO_RETRY.includes(path)) {
    try {
      await refreshSession();
    } catch {
      sessionEndHandler();
      return res;
    }
    res = await send(path, options);
  }
  return res;
}

export async function api(path, options = {}) {
  return parse(await request(path, options));
}

/** Fetches a protected binary (files are never public URLs); throws ApiError on failure. */
export async function getBlob(path) {
  const res = await request(path);
  if (!res.ok) await parse(res);
  return res.blob();
}

export const get = (path) => api(path);
export const post = (path, body) => api(path, { method: "POST", body });
export const patch = (path, body) => api(path, { method: "PATCH", body });
export const postForm = (path, formData) => api(path, { method: "POST", body: formData });

export function qs(params) {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") s.set(k, v);
  });
  const str = s.toString();
  return str ? `?${str}` : "";
}
