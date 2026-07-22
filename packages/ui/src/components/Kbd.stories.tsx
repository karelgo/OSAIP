import type { Meta, StoryObj } from "@storybook/react";
import { Kbd } from "./Kbd";

const meta = {
  title: "Components/Kbd",
  component: Kbd,
} satisfies Meta<typeof Kbd>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Single: Story = { args: { children: "⌘K" } };

export const Combos: Story = {
  render: () => (
    <div className="flex items-center gap-3 text-sm text-muted">
      <span className="inline-flex items-center gap-1">
        Build <Kbd>B</Kbd>
      </span>
      <span className="inline-flex items-center gap-1">
        Omnibar <Kbd>⌘K</Kbd>
      </span>
      <span className="inline-flex items-center gap-1">
        Inspector <Kbd>⏎</Kbd>
      </span>
      <span className="inline-flex items-center gap-1">
        Save <Kbd>⌘</Kbd>
        <Kbd>S</Kbd>
      </span>
    </div>
  ),
};
