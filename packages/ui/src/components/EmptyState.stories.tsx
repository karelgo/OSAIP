import type { Meta, StoryObj } from "@storybook/react";
import { Bot, Database } from "lucide-react";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

const meta = {
  title: "Components/EmptyState",
  component: EmptyState,
} satisfies Meta<typeof EmptyState>;
export default meta;

type Story = StoryObj<typeof meta>;

/** Empty states are starting points (§6.3(9)): 2-3 templates + a seed action. */
export const Datasets: Story = {
  render: () => (
    <div className="w-[32rem]">
      <EmptyState
        icon={<Database />}
        title="No datasets yet"
        description="Connect a source or upload a file to start building your Flow."
      >
        <Button>Upload a file</Button>
        <Button variant="secondary">Connect Postgres</Button>
        <Button variant="ghost">Browse S3</Button>
      </EmptyState>
    </div>
  ),
};

export const Agents: Story = {
  render: () => (
    <div className="w-[32rem]">
      <EmptyState
        icon={<Bot />}
        title="No agents in this project"
        description="Start from a template — every template ships with an eval set."
      >
        <Button>New agent from template</Button>
        <Button variant="secondary">Write a code agent</Button>
      </EmptyState>
    </div>
  ),
};

export const TitleOnly: Story = {
  render: () => (
    <div className="w-96">
      <EmptyState title="No runs match these filters" />
    </div>
  ),
};
