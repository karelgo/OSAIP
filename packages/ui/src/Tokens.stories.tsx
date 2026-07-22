import type * as React from "react";
import type { Meta, StoryObj } from "@storybook/react";

// Foundations page: renders the token contract itself — colors, spacing,
// radii, elevation, type, motion — straight from the CSS variables so what
// you see is exactly what ships. Flip the theme/density toolbars.

const meta = {
  title: "Foundations/Tokens",
  parameters: { layout: "padded" },
} satisfies Meta;
export default meta;

type Story = StoryObj<typeof meta>;

function Swatch({ name, border }: { name: string; border?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className="size-10 shrink-0 rounded-md"
        style={{
          background: `var(${name})`,
          boxShadow: border ? "inset 0 0 0 1px var(--color-border)" : undefined,
        }}
      />
      <code className="font-mono text-xs text-muted">{name}</code>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-fg">{title}</h2>
      {children}
    </section>
  );
}

export const Colors: Story = {
  render: () => (
    <div className="flex max-w-3xl flex-col gap-8">
      <Section title="Neutrals — graphite / off-white">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          <Swatch name="--color-bg" border />
          <Swatch name="--color-bg-subtle" border />
          <Swatch name="--color-surface" border />
          <Swatch name="--color-surface-raised" border />
          <Swatch name="--color-border" />
          <Swatch name="--color-border-strong" />
          <Swatch name="--color-text" />
          <Swatch name="--color-text-muted" />
          <Swatch name="--color-text-faint" />
        </div>
      </Section>
      <Section title="Accent — one violet-indigo family">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          <Swatch name="--color-accent" />
          <Swatch name="--color-accent-hover" />
          <Swatch name="--color-accent-subtle" border />
          <Swatch name="--color-accent-strong" />
          <Swatch name="--color-accent-text" border />
        </div>
      </Section>
      <Section title="Status palette — shared by jobs, evals, guardrails">
        <div className="flex flex-col gap-2">
          {(["info", "success", "warning", "danger"] as const).map((status) => (
            <div key={status} className="flex items-center gap-2">
              <Swatch name={`--color-status-${status}`} />
              <Swatch name={`--color-status-${status}-subtle`} border />
              <span
                className="rounded-sm px-2 py-0.5 text-xs font-medium"
                style={{
                  background: `var(--color-status-${status}-subtle)`,
                  color: `var(--color-status-${status})`,
                }}
              >
                Text on subtle (AA)
              </span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  ),
};

export const SpacingAndRadii: Story = {
  render: () => (
    <div className="flex max-w-3xl flex-col gap-8">
      <Section title="Spacing — 4px grid">
        <div className="flex items-end gap-2">
          {[1, 2, 3, 4, 6, 8, 10, 12, 16].map((step) => (
            <div key={step} className="flex flex-col items-center gap-1">
              <div className="w-6 rounded-sm bg-accent" style={{ height: `${step * 4}px` }} />
              <code className="font-mono text-[10px] text-faint">{step * 4}</code>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Radius scale">
        <div className="flex items-center gap-6">
          {(["sm", "md", "lg"] as const).map((r) => (
            <div key={r} className="flex flex-col items-center gap-1.5">
              <div
                className="size-16 border border-border-strong bg-surface"
                style={{ borderRadius: `var(--radius-${r})` }}
              />
              <code className="font-mono text-xs text-muted">--radius-{r}</code>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Elevation">
        <div className="flex items-center gap-6">
          {[1, 2, 3].map((level) => (
            <div key={level} className="flex flex-col items-center gap-1.5">
              <div
                className="size-20 rounded-lg bg-surface-raised"
                style={{ boxShadow: `var(--shadow-${level})` }}
              />
              <code className="font-mono text-xs text-muted">--shadow-{level}</code>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Density">
        <p className="text-sm text-muted">
          Controls are <code className="font-mono text-xs">var(--control-h)</code> tall
          (36px comfortable, 30px compact); table cells pad with{" "}
          <code className="font-mono text-xs">var(--cell-py)</code> (8px / 4px). Flip the
          density toolbar to compare.
        </p>
        <div className="flex h-control w-56 items-center rounded-md border border-border bg-surface px-3 text-sm text-muted">
          h-control sized box
        </div>
      </Section>
    </div>
  ),
};

export const Typography: Story = {
  render: () => (
    <div className="flex max-w-3xl flex-col gap-8">
      <Section title="IBM Plex Sans — UI">
        <div className="flex flex-col gap-1">
          <p className="text-2xl font-semibold text-fg">Flow builds only what is stale</p>
          <p className="text-base font-medium text-fg">Flow builds only what is stale</p>
          <p className="text-sm text-fg">Flow builds only what is stale — 400 body text</p>
          <p className="text-sm text-muted">Muted: descriptions and secondary labels</p>
          <p className="text-sm text-faint">Faint: placeholders and hints</p>
        </div>
      </Section>
      <Section title="IBM Plex Mono — code and data">
        <p className="font-mono text-sm text-fg">
          SELECT region, sum(revenue) FROM orders GROUP BY 1
        </p>
      </Section>
      <Section title="Tabular numerals (.tabular)">
        <div className="flex gap-8 text-sm">
          <div>
            <p className="mb-1 text-xs text-faint">proportional</p>
            <p className="text-fg">1,111,111.11</p>
            <p className="text-fg">8,808,808.80</p>
          </div>
          <div>
            <p className="mb-1 text-xs text-faint">.tabular</p>
            <p className="tabular text-fg">1,111,111.11</p>
            <p className="tabular text-fg">8,808,808.80</p>
          </div>
        </div>
      </Section>
      <Section title="Motion — 120 to 200 ms">
        <p className="text-sm text-muted">
          <code className="font-mono text-xs">--motion-fast: 120ms</code> ·{" "}
          <code className="font-mono text-xs">--motion-normal: 160ms</code> ·{" "}
          <code className="font-mono text-xs">--motion-slow: 200ms</code> — all zeroed under{" "}
          <code className="font-mono text-xs">prefers-reduced-motion</code>.
        </p>
      </Section>
    </div>
  ),
};
