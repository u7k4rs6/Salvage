// The one place that talks to the API.
//
// Two rules from docs/03_SECURITY_AND_ACCESS.md section 9 and docs/04_FRONTEND_SPEC.md section 3:
// the token lives in React state only, never in localStorage, and it is attached to mutating
// calls only. A failed call carries the server's message and, when the server sent one, a request
// id, because an error panel that says "something went wrong" is not an ops tool.

export class ApiError extends Error {
  status: number;
  requestId: string | null;

  constructor(message: string, status: number, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

async function parse(response: Response): Promise<any> {
  const text = await response.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail =
      (body && (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))) ||
      text ||
      response.statusText;
    throw new ApiError(detail, response.status, response.headers.get("x-request-id"));
  }
  return body;
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  return parse(response) as Promise<T>;
}

export async function post<T>(path: string, body?: unknown, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body ?? {}),
  });
  return parse(response) as Promise<T>;
}

export function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const requestId = error.requestId ? ` (request ${error.requestId})` : "";
    if (error.status === 401) return "This action needs the dashboard token. Enter it above.";
    if (error.status === 403) return "The token was rejected.";
    if (error.status === 503) return `${error.message}`;
    return `${error.message}${requestId}`;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}
