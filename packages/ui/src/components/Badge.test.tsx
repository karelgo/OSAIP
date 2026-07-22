import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("defaults to the neutral variant", () => {
    render(<Badge>Draft</Badge>);
    expect(screen.getByText("Draft").className).toContain("bg-bg-subtle");
  });

  it("maps each severity to its status palette classes", () => {
    const cases = [
      ["info", "bg-status-info-subtle", "text-status-info"],
      ["success", "bg-status-success-subtle", "text-status-success"],
      ["warning", "bg-status-warning-subtle", "text-status-warning"],
      ["danger", "bg-status-danger-subtle", "text-status-danger"],
    ] as const;
    for (const [variant, bg, text] of cases) {
      const { unmount } = render(<Badge variant={variant}>{variant}</Badge>);
      const el = screen.getByText(variant);
      expect(el.className).toContain(bg);
      expect(el.className).toContain(text);
      unmount();
    }
  });

  it("styles the accent variant from the accent palette, not the status one", () => {
    render(<Badge variant="accent">Certified</Badge>);
    const el = screen.getByText("Certified");
    expect(el.className).toContain("bg-accent-subtle");
    expect(el.className).toContain("text-accent-strong");
  });
});
