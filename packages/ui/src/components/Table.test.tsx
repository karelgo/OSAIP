import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Table, TBody, TD, TH, THead, TR } from "./Table";

describe("Table", () => {
  it("applies tabular numerals and right alignment on numeric cells", () => {
    render(
      <Table>
        <THead>
          <TR>
            <TH>Dataset</TH>
            <TH numeric>Rows</TH>
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD>orders_clean</TD>
            <TD numeric>120409</TD>
          </TR>
        </TBody>
      </Table>,
    );
    const th = screen.getByText("Rows");
    expect(th.className).toContain("tabular");
    expect(th.className).toContain("text-right");
    const td = screen.getByText("120409");
    expect(td.className).toContain("tabular");
    expect(td.className).toContain("text-right");
    // non-numeric cells stay left-aligned without tabular
    expect(screen.getByText("orders_clean").className).not.toContain("tabular");
  });

  it("marks header cells sticky when stickyHeader is set", () => {
    render(
      <Table stickyHeader>
        <THead data-testid="head">
          <TR>
            <TH>Dataset</TH>
          </TR>
        </THead>
        <TBody>
          <TR>
            <TD>orders_clean</TD>
          </TR>
        </TBody>
      </Table>,
    );
    expect(screen.getByTestId("head").className).toContain("[&_th]:sticky");
  });
});
