// Local Tailwind config for this package's own Storybook and stories.
// Consumers use `@osaip/ui/tailwind-preset` with their own content globs.
import type { Config } from "tailwindcss";
import preset from "./tailwind-preset";

export default {
  presets: [preset],
  content: ["./src/**/*.{ts,tsx}", "./.storybook/**/*.{ts,tsx}"],
} satisfies Config;
