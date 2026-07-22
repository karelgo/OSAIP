import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Field, Input } from "./Input";

describe("Field", () => {
  it("associates the label with the control", () => {
    render(
      <Field label="Project name">
        <Input />
      </Field>,
    );
    expect(screen.getByLabelText("Project name")).toBeInstanceOf(HTMLInputElement);
  });

  it("wires aria-describedby and aria-invalid when an error is shown", () => {
    render(
      <Field label="Project name" error="Enter a project name">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText("Project name");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const errorEl = document.getElementById(describedBy as string);
    expect(errorEl?.textContent).toBe("Enter a project name");
  });

  it("points aria-describedby at the hint when there is no error", () => {
    render(
      <Field label="Project key" hint="Lowercase letters and dashes">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText("Project key");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    const describedBy = input.getAttribute("aria-describedby");
    const hintEl = document.getElementById(describedBy as string);
    expect(hintEl?.textContent).toBe("Lowercase letters and dashes");
  });
});
