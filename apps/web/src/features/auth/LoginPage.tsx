// Sign-in — the OIDC dance is entirely server-side (ADR-0001); this screen only
// forwards to it, honoring the deep link the user originally wanted.
import { Button } from "@osaip/ui";
import { useSearch } from "@tanstack/react-router";
import { loginUrl } from "./api";

export function LoginPage() {
  const { next } = useSearch({ from: "/login" }) as { next?: string };
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg text-text">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8 shadow-2">
        <h1 className="text-xl font-semibold tracking-tight">OSAIP</h1>
        <p className="mt-1 text-sm text-muted">
          The open source AI platform. Sign in with your organization account.
        </p>
        <Button
          className="mt-6 w-full"
          data-testid="login-button"
          onClick={() => window.location.assign(loginUrl(next ?? "/"))}
        >
          Sign in
        </Button>
      </div>
    </main>
  );
}
