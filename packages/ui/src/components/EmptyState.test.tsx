import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders title, description, and CTA children", () => {
    render(
      <EmptyState title="No datasets yet" description="Connect a source or upload a file.">
        <Button>Upload a file</Button>
        <Button variant="secondary">Connect Postgres</Button>
      </EmptyState>,
    );
    expect(screen.getByRole("heading", { name: "No datasets yet" })).toBeTruthy();
    expect(screen.getByText("Connect a source or upload a file.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Upload a file" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect Postgres" })).toBeTruthy();
  });
});
