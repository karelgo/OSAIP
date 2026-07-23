// Workspace-wide flat config. Generated code is excluded; @osaip/api-client output is
// machine-written by hey-api (spec §3.2: hand-written fetch is forbidden, so humans
// never edit it either).
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "**/storybook-static/**",
      "packages/api-client/src/generated/**",
      "**/*.gen.ts",
      ".venv/**",
      "**/__pycache__/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.es2022 } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["**/*.{js,cjs,mjs}", "**/*.config.{ts,js,cjs,mjs}", "**/.storybook/**"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    // Playwright specs are glue over the untyped API JSON (the generated client isn't
    // used here — we exercise the wire contract directly), so `any` is expected.
    files: ["apps/web/e2e/**/*.ts"],
    languageOptions: { globals: { ...globals.node } },
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
);
