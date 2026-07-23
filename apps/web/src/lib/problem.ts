// problem+json helpers: the generated client (throwOnError) rethrows the parsed
// RFC 9457 body, so errors carry title/detail/hint straight from the API.
import { toast } from "@osaip/ui";

export interface ProblemDetails {
  title?: string;
  detail?: string;
  hint?: string;
  status?: number;
}

export function asProblem(error: unknown): ProblemDetails {
  return (typeof error === "object" && error !== null ? error : {}) as ProblemDetails;
}

/** Standard error toast for a failed mutation: problem title + detail + hint (§6.5). */
export function problemToast(error: unknown, fallback: string): void {
  const problem = asProblem(error);
  const description = [problem.detail, problem.hint].filter(Boolean).join(" ");
  toast({
    title: problem.title ?? fallback,
    description: description || undefined,
    severity: "error",
  });
}
