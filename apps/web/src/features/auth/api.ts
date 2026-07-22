// Auth data access — thin composition over the GENERATED client (§3.2: hand-written
// fetch is forbidden; these are the only symbols auth screens import).
import { getMeOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";

export function useMe() {
  return useQuery({
    ...getMeOptions(),
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (isUnauthenticated(error)) return false;
      return failureCount < 2;
    },
  });
}

export function isUnauthenticated(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status?: unknown }).status === 401
  );
}

export function loginUrl(next: string): string {
  return `/api/v1/auth/login?next=${encodeURIComponent(next)}`;
}
