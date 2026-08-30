import { FULL_CONSOLE } from "./build";
import resultsFixtureUrl from "../board/fixtures/results.api.json?url";

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

/**
 * The demo build has no API, and Results is one of its two pages.
 *
 * Everything else the demo ships reads a committed recording directly. Results reads the sweep
 * through `/api/results`, and in a static deployment that fetch 404s, which Results renders as
 * "Nothing here yet." twice. An empty Results page is the worst thing this project could show a
 * stranger: it reads as a project with no measurements, when the measurements are the strongest
 * part of it.
 *
 * So in a build with no backend those two paths are answered from a committed capture of the same
 * routes, taken verbatim from the API reading `data/results/`. Nothing is recomputed here and no
 * other path is intercepted: a call to any other route in a demo build still fails, and should.
 */
let resultsFixture: Promise<any> | null = null;

async function demoResults(path: string): Promise<any> {
  if (resultsFixture === null) {
    resultsFixture = fetch(resultsFixtureUrl).then((response) => {
      if (!response.ok) {
        throw new ApiError(`recorded results unavailable`, response.status);
      }
      return response.json();
    });
  }
  const doc = await resultsFixture;
  if (path === "/api/results") return doc["GET /api/results"];
  const runId = decodeURIComponent(path.slice("/api/results/".length));
  const run = doc.runs?.[runId];
  if (!run) throw new ApiError(`no recorded results for run ${runId}`, 404);
  return run;
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!FULL_CONSOLE && path.startsWith("/api/results")) {
    return demoResults(path) as Promise<T>;
  }
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
