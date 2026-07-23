// Monaco, self-hosted (no CDN fetch → CSP-safe, ADR-0001) and lazy: this module is
// only pulled in behind React.lazy for SQL/Python recipes, so monaco never touches
// the flow chunk, let alone the entry chunk. Vite's `?worker` import bundles the
// editor worker same-origin.
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
// monaco@0.56 ships an `exports` map that remaps `./*` → `./esm/vs/*.js`, so the
// worker's importable subpath drops the physical `esm/vs` prefix. Vite bundles the
// worker same-origin (no CDN), keeping it CSP-safe.
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

(self as typeof self & { MonacoEnvironment?: monaco.Environment }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};
loader.config({ monaco });

export interface CodeEditorProps {
  value: string;
  language: "sql" | "python";
  onChange: (value: string) => void;
  colorMode: "light" | "dark";
  readOnly?: boolean;
  "data-testid"?: string;
}

export default function CodeEditor({
  value,
  language,
  onChange,
  colorMode,
  readOnly = false,
  "data-testid": testId,
}: CodeEditorProps) {
  return (
    <div
      data-testid={testId}
      className="overflow-hidden rounded-md border border-border"
    >
      <Editor
        height="16rem"
        language={language}
        value={value}
        theme={colorMode === "dark" ? "vs-dark" : "vs"}
        onChange={(next) => onChange(next ?? "")}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 13,
          fontFamily: "var(--font-mono)",
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "on",
          lineNumbers: "on",
          tabSize: 2,
          padding: { top: 8, bottom: 8 },
        }}
      />
    </div>
  );
}
