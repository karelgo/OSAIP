import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Vitest globals are off (explicit imports per project convention), so RTL
// auto-cleanup does not register itself; do it here.
afterEach(() => {
  cleanup();
});
