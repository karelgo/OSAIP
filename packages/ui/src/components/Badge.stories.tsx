import type { Meta, StoryObj } from "@storybook/react";
import { Badge } from "./Badge";

const meta = {
  title: "Components/Badge",
  component: Badge,
} satisfies Meta<typeof Badge>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Neutral: Story = { args: { children: "Draft", variant: "neutral" } };
export const Accent: Story = { args: { children: "Certified", variant: "accent" } };
export const Info: Story = { args: { children: "Queued", variant: "info" } };
export const Success: Story = { args: { children: "Succeeded", variant: "success" } };
export const Warning: Story = { args: { children: "Stale", variant: "warning" } };
export const Danger: Story = { args: { children: "Failed", variant: "danger" } };

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="neutral">Draft</Badge>
      <Badge variant="accent">Certified</Badge>
      <Badge variant="info">Queued</Badge>
      <Badge variant="success">Succeeded</Badge>
      <Badge variant="warning">Stale</Badge>
      <Badge variant="danger">Failed</Badge>
    </div>
  ),
};
