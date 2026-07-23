// Small columns+rows grid shared by the inspector's Preview tab (recipe preview and
// dataset sample). Same sticky-header scroll style as the datasets sample grid.
import { TBody, TD, TH, THead, TR } from "@osaip/ui";
import { PlainTable, STICKY_THEAD, ScrollRegion } from "../../lib/ScrollRegion";
import { formatValue } from "../datasets/lib";

export interface PreviewColumn {
  name: string;
  type?: string;
  classification?: string;
}

export function PreviewGrid({
  columns,
  rows,
  label,
  "data-testid": testId,
}: {
  columns: PreviewColumn[];
  rows: Array<Record<string, unknown>>;
  label: string;
  "data-testid"?: string;
}) {
  return (
    <ScrollRegion
      label={label}
      data-testid={testId}
      className="max-h-[24rem] rounded-md border border-border"
    >
      <PlainTable>
        <THead className={STICKY_THEAD}>
          <TR>
            {columns.map((column) => (
              <TH key={column.name} className="whitespace-nowrap font-mono text-xs">
                {column.name}
                {column.type ? (
                  <span className="ml-1 font-normal text-faint">{column.type}</span>
                ) : null}
              </TH>
            ))}
          </TR>
        </THead>
        <TBody>
          {rows.map((row, index) => (
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
  );
}
