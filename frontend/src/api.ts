export const prefix = import.meta.env.DEV ? "/api" : "";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    timeout?: number;
  } = {},
): Promise<T> {
  const signal = options.signal
    ? AbortSignal.any([
        options.signal,
        AbortSignal.timeout(options.timeout ?? 25000),
      ])
    : AbortSignal.timeout(options.timeout ?? 25000);
  const response = await fetch(prefix + path, {
    method: options.method ?? "GET",
    signal,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const result = await response.json();
  if (!response.ok || result.status === "error")
    throw new ApiError(
      result.error?.message ?? `Request failed (${response.status})`,
      response.status,
    );
  return result.output as T;
}
export const messageOf = (error: unknown) =>
  error instanceof Error
    ? error.name === "TimeoutError"
      ? "The request timed out, but the server may still be working. Refresh the version list instead of running it again."
      : error.message
    : "The request did not complete. Please try again.";
