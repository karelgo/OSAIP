import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "./Button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./Tooltip";

const meta = {
  title: "Components/Tooltip",
  component: Tooltip,
  decorators: [
    (Story) => (
      <TooltipProvider delayDuration={200}>
        <Story />
      </TooltipProvider>
    ),
  ],
} satisfies Meta<typeof Tooltip>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost">Why?</Button>
      </TooltipTrigger>
      <TooltipContent>Opens the trace for this answer</TooltipContent>
    </Tooltip>
  ),
};

export const Sides: Story = {
  render: () => (
    <div className="flex items-center gap-4">
      {(["top", "right", "bottom", "left"] as const).map((side) => (
        <Tooltip key={side}>
          <TooltipTrigger asChild>
            <Button variant="secondary">{side}</Button>
          </TooltipTrigger>
          <TooltipContent side={side}>Shown on {side}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  ),
};
