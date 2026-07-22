import type { Meta, StoryObj } from "@storybook/react";
import { Spinner } from "./Spinner";

const meta = {
  title: "Components/Spinner",
  component: Spinner,
} satisfies Meta<typeof Spinner>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { label: "Loading" } };

export const Sizes: Story = {
  render: () => (
    <div className="flex items-center gap-4 text-muted">
      <Spinner className="size-4" label="Loading" />
      <Spinner className="size-6" label="Loading" />
      <Spinner className="size-8" label="Loading" />
    </div>
  ),
};
