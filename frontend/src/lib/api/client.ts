import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** All requests go to /api/v1 on the page's own origin; Next forwards them to the local API. */
export function apiOrigin(): string {
  return typeof window === "undefined" ? "http://127.0.0.1:3000" : window.location.origin;
}

export const api = createClient<paths>({ baseUrl: apiOrigin() });

export type ErrorKind = "http" | "network";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
    readonly requestId?: string,
    readonly kind: ErrorKind = "http",
  ) {
    super(message);
  }

  get isUnavailable(): boolean {
    return this.status === 503;
  }

  get isValidation(): boolean {
    return this.status === 422;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
}

type ErrorEnvelope = { error?: { code?: string; message?: string; details?: unknown; request_id?: string } };

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof DOMException && err.name === "AbortError") return new ApiError(0, "aborted", "Request cancelled", undefined, undefined, "network");
  return new ApiError(0, "network_error",
    "The SocietyTwin API could not be reached. Check that the local API service is running, then retry.",
    undefined, undefined, "network");
}

/** Unwraps an openapi-fetch result, turning the API's error envelope into ApiError. */
export async function unwrap<T>(pending: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await pending;
  } catch (err) {
    throw toApiError(err);
  }
  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    const env = (error ?? {}) as ErrorEnvelope;
    throw new ApiError(
      response.status,
      env.error?.code ?? `http_${response.status}`,
      env.error?.message ?? `Request failed with status ${response.status}`,
      env.error?.details,
      env.error?.request_id,
    );
  }
  return data as T;
}

/** Turn validation details into readable lines (never echoing request bodies). */
export function describeDetails(details: unknown): string[] {
  if (Array.isArray(details)) {
    return details.map((d) => {
      if (d && typeof d === "object" && "msg" in d) {
        const loc = Array.isArray((d as { loc?: unknown }).loc) ? ((d as { loc: string[] }).loc).filter((x) => x !== "body").join(" › ") : "";
        return loc ? `${loc}: ${(d as { msg: string }).msg}` : String((d as { msg: string }).msg);
      }
      return String(d);
    });
  }
  if (details && typeof details === "object") {
    const obj = details as Record<string, unknown>;
    const lines: string[] = [];
    for (const key of ["reasons", "blockers"]) {
      const list = obj[key];
      if (Array.isArray(list)) {
        for (const item of list) {
          lines.push(typeof item === "string" ? item : (item as { message?: string }).message ?? JSON.stringify(item));
        }
      }
    }
    for (const key of ["runner_message", "adapter_message", "detail"]) {
      if (typeof obj[key] === "string" && obj[key]) lines.push(String(obj[key]));
    }
    return lines;
  }
  return [];
}
