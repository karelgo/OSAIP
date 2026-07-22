import type { Meta, StoryObj } from "@storybook/react";
import { Skeleton } from "./Skeleton";

const meta = {
  title: "Components/Skeleton",
  component: Skeleton,
} satisfies Meta<typeof Skeleton>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Block: Story = {
  render: () => <Skeleton className="h-24 w-72" />,
};

export const TextLines: Story = {
  render: () => (
    <div className="flex w-72 flex-col gap-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  ),
};

export const CardShape: Story = {
  render: () => (
    <div className="flex w-80 flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center gap-3">
        <Skeleton className="size-8 rounded-full" />
        <Skeleton className="h-4 w-40" />
      </div>
      <Skeleton className="h-20 w-full" />
      <div className="flex gap-2">
        <Skeleton className="h-7 w-24" />
        <Skeleton className="h-7 w-16" />
      </div>
    </div>
  ),
};
