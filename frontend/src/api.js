// Every call goes to /api on the page's own origin; nginx (or Vite in development) forwards it to
// api-service. See nginx.conf and vite.config.js.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function getJson(path) {
  let response;
  try {
    response = await fetch(`/api${path}`);
  } catch {
    throw new ApiError("The API cannot be reached.", 0);
  }
  if (!response.ok) {
    // FastAPI puts its reason in "detail" (the 404 for an unknown docket names the indexed ones).
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(detail || `HTTP ${response.status}`, response.status);
  }
  return response.json();
}
