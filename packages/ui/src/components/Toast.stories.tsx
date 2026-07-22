import type { Meta, StoryObj } from "@storybook/react";
import { toast } from "../lib/toast-store";
import { Button } from "./Button";
import { Toaster } from "./Toast";

const meta = {
  title: "Components/Toast",
  component: Toaster,
  decorators: [
    (Story) => (
      <>
        <Story />
        <Toaster />
      </>
    ),
  ],
} satisfies Meta<typeof Toaster>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Severities: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="secondary"
        onClick={() => toast({ title: "Build queued", description: "orders_clean v4" })}
      >
        Show info toast
      </Button>
      <Button
        variant="secondary"
        onClick={() =>
          toast({
            title: "Build finished",
            description: "orders_clean built in 3.2s",
            severity: "success",
          })
        }
      >
        Show success toast
      </Button>
      <Button
        variant="secondary"
        onClick={() =>
          toast({
            title: "Quota at 80%",
            description: "This project is close to its monthly LLM budget.",
            severity: "warning",
          })
        }
      >
        Show warning toast
      </Button>
      <Button
        variant="secondary"
        onClick={() =>
          toast({
            title: "Build failed",
            description: "orders_clean step 2: column price not found.",
            severity: "error",
          })
        }
      >
        Show error toast
      </Button>
    </div>
  ),
};

export const WithAction: Story = {
  render: () => (
    <Button
      variant="secondary"
      onClick={() =>
        toast({
          title: "Build finished",
          description: "Deep-links into the run drawer (§6.3(4)).",
          severity: "success",
          action: { label: "Open run", onClick: () => undefined },
        })
      }
    >
      Show toast with action
    </Button>
  ),
};
