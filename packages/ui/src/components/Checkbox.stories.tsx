import type { Meta, StoryObj } from "@storybook/react";
import { Checkbox } from "./Checkbox";

const meta = {
  title: "Components/Checkbox",
  component: Checkbox,
} satisfies Meta<typeof Checkbox>;
export default meta;

type Story = StoryObj<typeof meta>;

export const WithLabel: Story = {
  args: { label: "Rebuild stale datasets only" },
};

export const Checked: Story = {
  args: { label: "Rebuild stale datasets only", defaultChecked: true },
};

export const Indeterminate: Story = {
  args: { label: "Select all datasets", checked: "indeterminate" },
};

export const Disabled: Story = {
  args: { label: "Requires editor role", disabled: true },
};

export const Bare: Story = {
  args: { "aria-label": "Select row" },
};
