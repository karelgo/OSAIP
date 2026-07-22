// Token contract test — tokens.css is the design contract (§6.4, LOCKED).
// If this fails, a token was renamed or dropped; that is a breaking change.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("./tokens.css", import.meta.url)), "utf8");

/** Extract the balanced `{ ... }` body following the first occurrence of `selector`. */
function blockFor(source: string, selector: string): string {
  const start = source.indexOf(selector);
  if (start === -1) throw new Error(`selector not found: ${selector}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced block for: ${selector}`);
}

const THEME_VARS = [
  // graphite/off-white neutral scale
  "--color-bg",
  "--color-bg-subtle",
  "--color-surface",
  "--color-surface-raised",
  "--color-border",
  "--color-border-strong",
  "--color-text",
  "--color-text-muted",
  "--color-text-faint",
  // one accent (violet-indigo)
  "--color-accent",
  "--color-accent-hover",
  "--color-accent-subtle",
  "--color-accent-text",
  // semantic status palette + subtle backgrounds
  "--color-status-info",
  "--color-status-info-subtle",
  "--color-status-success",
  "--color-status-success-subtle",
  "--color-status-warning",
  "--color-status-warning-subtle",
  "--color-status-danger",
  "--color-status-danger-subtle",
  // elevation is theme-dependent
  "--shadow-1",
  "--shadow-2",
  "--shadow-3",
];

const STATIC_VARS = [
  "--radius-sm",
  "--radius-md",
  "--radius-lg",
  "--font-sans",
  "--font-mono",
  "--motion-fast",
  "--motion-normal",
  "--motion-slow",
  "--control-h",
  "--cell-py",
];

describe("tokens.css contract", () => {
  const root = blockFor(css, ":root");
  const dark = blockFor(css, '[data-theme="dark"]');

  it("defines every required variable in :root", () => {
    for (const name of [...THEME_VARS, ...STATIC_VARS]) {
      expect(root, `missing ${name} in :root`).toContain(`${name}:`);
    }
  });

  it('overrides every theme-dependent variable in [data-theme="dark"]', () => {
    for (const name of THEME_VARS) {
      expect(dark, `missing ${name} in [data-theme="dark"]`).toContain(`${name}:`);
    }
  });

  it('mirrors the dark theme for [data-theme="system"] under prefers-color-scheme', () => {
    const media = blockFor(css, "@media (prefers-color-scheme: dark)");
    expect(media).toContain('[data-theme="system"]');
    const system = blockFor(media, '[data-theme="system"]');
    for (const name of THEME_VARS) {
      expect(system, `missing ${name} in [data-theme="system"]`).toContain(`${name}:`);
    }
    // Dark and system-dark must define identical values (kept in sync by hand).
    for (const name of THEME_VARS) {
      const pattern = new RegExp(`${name}:\\s*([^;]+);`);
      const inDark = dark.match(pattern)?.[1]?.trim();
      const inSystem = system.match(pattern)?.[1]?.trim();
      expect(inSystem, `${name} diverged between dark and system-dark`).toBe(inDark);
    }
  });

  it("zeroes transitions and animations under prefers-reduced-motion", () => {
    const reduced = blockFor(css, "@media (prefers-reduced-motion: reduce)");
    expect(reduced).toContain("animation-duration");
    expect(reduced).toContain("transition-duration");
    expect(reduced).toContain("animation-iteration-count: 1");
  });

  it("keeps motion durations within the 120-200ms band, ordered", () => {
    const value = (name: string): number => {
      const match = root.match(new RegExp(`${name}:\\s*(\\d+)ms`));
      if (!match) throw new Error(`${name} missing or not in ms`);
      return Number(match[1]);
    };
    const fast = value("--motion-fast");
    const normal = value("--motion-normal");
    const slow = value("--motion-slow");
    for (const ms of [fast, normal, slow]) {
      expect(ms).toBeGreaterThanOrEqual(120);
      expect(ms).toBeLessThanOrEqual(200);
    }
    expect(fast).toBeLessThanOrEqual(normal);
    expect(normal).toBeLessThanOrEqual(slow);
  });

  it("tightens density variables under [data-density=compact]", () => {
    const compact = blockFor(css, '[data-density="compact"]');
    expect(compact).toContain("--control-h:");
    expect(compact).toContain("--cell-py:");
  });
});
