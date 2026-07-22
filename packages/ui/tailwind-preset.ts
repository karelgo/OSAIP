// @osaip/ui Tailwind preset — maps the token CSS variables (src/styles/tokens.css,
// the design contract) into the Tailwind theme so app code writes `bg-surface
// text-muted border-border` and stays theme/density-agnostic. Consumers add this
// to `presets` in their tailwind config and import "@osaip/ui/styles.css".
import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

const preset = {
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "var(--color-bg)",
          subtle: "var(--color-bg-subtle)",
        },
        surface: {
          DEFAULT: "var(--color-surface)",
          raised: "var(--color-surface-raised)",
        },
        border: {
          DEFAULT: "var(--color-border)",
          strong: "var(--color-border-strong)",
        },
        // Foreground scale; `muted`/`faint` are aliased top-level so `text-muted`
        // and `text-faint` read naturally in app code.
        fg: {
          DEFAULT: "var(--color-text)",
          muted: "var(--color-text-muted)",
          faint: "var(--color-text-faint)",
        },
        muted: "var(--color-text-muted)",
        faint: "var(--color-text-faint)",
        accent: {
          DEFAULT: "var(--color-accent)",
          hover: "var(--color-accent-hover)",
          subtle: "var(--color-accent-subtle)",
          strong: "var(--color-accent-strong)",
          text: "var(--color-accent-text)",
        },
        // Solid danger action color (buttons) — kept separate from the status
        // palette because status colors are tuned as text-on-subtle in both themes.
        "danger-solid": {
          DEFAULT: "var(--color-danger-solid)",
          hover: "var(--color-danger-solid-hover)",
        },
        status: {
          info: {
            DEFAULT: "var(--color-status-info)",
            subtle: "var(--color-status-info-subtle)",
          },
          success: {
            DEFAULT: "var(--color-status-success)",
            subtle: "var(--color-status-success-subtle)",
          },
          warning: {
            DEFAULT: "var(--color-status-warning)",
            subtle: "var(--color-status-warning-subtle)",
          },
          danger: {
            DEFAULT: "var(--color-status-danger)",
            subtle: "var(--color-status-danger-subtle)",
          },
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius-md)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        "1": "var(--shadow-1)",
        "2": "var(--shadow-2)",
        "3": "var(--shadow-3)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      transitionDuration: {
        DEFAULT: "var(--motion-normal)",
        fast: "var(--motion-fast)",
        normal: "var(--motion-normal)",
        slow: "var(--motion-slow)",
      },
      // Density-aware sizing: h-control follows --control-h, py-cell-y follows
      // --cell-py; both tighten under [data-density="compact"].
      spacing: {
        control: "var(--control-h)",
        "cell-y": "var(--cell-py)",
      },
      ringColor: {
        DEFAULT: "var(--color-accent)",
      },
      ringOffsetColor: {
        DEFAULT: "var(--color-bg)",
      },
    },
  },
  plugins: [animate],
} satisfies Omit<Config, "content">;

export default preset;
