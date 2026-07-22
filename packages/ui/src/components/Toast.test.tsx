import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearToasts, dismissToast, getToasts, toast } from "../lib/toast-store";
import { Toaster } from "./Toast";

describe("toast store", () => {
  beforeEach(() => {
    clearToasts();
  });

  it("toast() adds an item with info severity by default", () => {
    const id = toast({ title: "Build queued" });
    const items = getToasts();
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ id, title: "Build queued", severity: "info" });
  });

  it("dismissToast() removes the item", () => {
    const id = toast({ title: "Build queued" });
    toast({ title: "Build started" });
    dismissToast(id);
    const items = getToasts();
    expect(items).toHaveLength(1);
    expect(items[0]?.title).toBe("Build started");
  });

  it("renders through the Toaster with the severity left border", () => {
    render(<Toaster />);
    act(() => {
      toast({ title: "Build finished", severity: "success" });
    });
    const title = screen.getByText("Build finished");
    const root = title.closest("li");
    expect(root).not.toBeNull();
    expect(root?.className).toContain("border-l-status-success");
  });

  it("maps error severity to the danger border", () => {
    render(<Toaster />);
    act(() => {
      toast({ title: "Build failed", severity: "error" });
    });
    const root = screen.getByText("Build failed").closest("li");
    expect(root?.className).toContain("border-l-status-danger");
  });
});
