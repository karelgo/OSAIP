// Preview-first block (§6.3(3) LOCKED): inferred TYPED schema + sample rows are
// shown before anything is built. Shared by the upload and register panels.
// Height-capped grids scroll inside focusable regions (axe: keyboard access).
import { TBody, TD, TH, THead, TR } from "@osaip/ui";
import type { ColumnOut } from "@osaip/api-client";
import { PlainTable, STICKY_THEAD, ScrollRegion } from "../../lib/ScrollRegion";
import { formatValue } from "./lib";

export function SchemaPreview({
  columns,
  preview,
  testId,
}: {
  columns: ColumnOut[];
  preview: Array<Record<string, unknown>>;
  testId: string;
}) {
  return (
    <div className="space-y-4" data-testid={testId}>
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
          Inferred schema
        </h3>
        <ScrollRegion
          label="Inferred schema"
          className="mt-2 max-h-48 rounded-md border border-border"
        >
          <PlainTable>
            <THead className={STICKY_THEAD}>
              <TR>
                <TH>Column</TH>
                <TH>Type</TH>
                <TH>Nullable</TH>
              </TR>
            </THead>
            <TBody>
              {columns.map((column) => (
                <TR key={column.name}>
                  <TD className="font-mono text-xs">{column.name}</TD>
                  <TD className="font-mono text-xs text-muted">{column.type}</TD>
                  <TD className="text-xs text-muted">
                    {column.nullable === false ? "no" : "yes"}
                  </TD>
                </TR>
              ))}
            </TBody>
          </PlainTable>
        </ScrollRegion>
      </section>
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
          Preview · first {preview.length} rows
        </h3>
        <ScrollRegion
          label="Preview rows"
          className="mt-2 max-h-56 rounded-md border border-border"
        >
          <PlainTable>
            <THead className={STICKY_THEAD}>
              <TR>
                {columns.map((column) => (
                  <TH key={column.name} className="whitespace-nowrap font-mono text-xs">
                    {column.name}
                  </TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {preview.map((row, index) => (
                <TR key={index}>
                  {columns.map((column) => (
                    <TD
                      key={column.name}
                      className="whitespace-nowrap font-mono text-xs tabular-nums"
                    >
                      {formatValue(row[column.name])}
                    </TD>
                  ))}
                </TR>
              ))}
            </TBody>
          </PlainTable>
        </ScrollRegion>
      </section>
    </div>
  );
}
