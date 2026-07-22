import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  it("renders each variant with its palette classes", () => {
    const { rerender } = render(<Button variant="primary">Save changes</Button>);
    expect(screen.getByRole("button").className).toContain("bg-accent");

    rerender(<Button variant="secondary">Save changes</Button>);
    expect(screen.getByRole("button").className).toContain("border-border");

    rerender(<Button variant="ghost">Save changes</Button>);
    expect(screen.getByRole("button").className).toContain("hover:bg-bg-subtle");

    rerender(<Button variant="danger">Delete project</Button>);
    expect(screen.getByRole("button").className).toContain("bg-danger-solid");
  });

  it("fires onClick", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save changes</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("blocks clicks when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Save changes
      </Button>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("shows a spinner, sets aria-busy, and blocks clicks while loading", () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Save changes
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.querySelector(".animate-spin")).not.toBeNull();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders the child element via asChild", () => {
    render(
      <Button asChild>
        <a href="/projects">Open projects</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Open projects" });
    expect(link.className).toContain("bg-accent");
  });
});
