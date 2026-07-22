import type { Meta, StoryObj } from "@storybook/react";
import { Badge } from "./Badge";
import { Table, TBody, TD, TH, THead, TR } from "./Table";

const meta = {
  title: "Components/Table",
  component: Table,
} satisfies Meta<typeof Table>;
export default meta;

type Story = StoryObj<typeof meta>;

const rows = [
  { name: "orders_raw", status: "success", rows: 120409, cost: "0.42" },
  { name: "orders_clean", status: "success", rows: 118221, cost: "1.03" },
  { name: "orders_enriched", status: "warning", rows: 118221, cost: "8.90" },
  { name: "churn_features", status: "danger", rows: 0, cost: "0.00" },
] as const;

const statusLabel = { success: "Succeeded", warning: "Stale", danger: "Failed" } as const;

export const Default: Story = {
  render: () => (
    <div className="w-[36rem]">
      <Table>
        <THead>
          <TR>
            <TH>Dataset</TH>
            <TH>Status</TH>
            <TH numeric>Rows</TH>
            <TH numeric>Cost (€)</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={row.name}>
              <TD className="font-medium">{row.name}</TD>
              <TD>
                <Badge variant={row.status}>{statusLabel[row.status]}</Badge>
              </TD>
              <TD numeric>{row.rows.toLocaleString("en-US")}</TD>
              <TD numeric>{row.cost}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  ),
};

export const StickyHeader: Story = {
  render: () => (
    <div className="w-[36rem]">
      <Table stickyHeader containerClassName="max-h-48 rounded-md border border-border">
        <THead>
          <TR>
            <TH>Dataset</TH>
            <TH numeric>Rows</TH>
          </TR>
        </THead>
        <TBody>
          {Array.from({ length: 20 }, (_, i) => (
            <TR key={i}>
              <TD>dataset_{i + 1}</TD>
              <TD numeric>{((i + 1) * 1042).toLocaleString("en-US")}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  ),
};

/** Toggle the density toolbar to see --cell-py tighten row padding. */
export const DensityAware: Story = {
  render: () => (
    <div className="w-[28rem]">
      <Table>
        <THead>
          <TR>
            <TH>Metric</TH>
            <TH numeric>Value</TH>
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD>Tokens in</TD>
            <TD numeric>18204</TD>
          </TR>
          <TR>
            <TD>Tokens out</TD>
            <TD numeric>1233</TD>
          </TR>
          <TR>
            <TD>Latency p95 (ms)</TD>
            <TD numeric>412</TD>
          </TR>
        </TBody>
      </Table>
    </div>
  ),
};
