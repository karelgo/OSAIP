import type { Meta, StoryObj } from "@storybook/react";
import { Plus } from "lucide-react";
import { Button } from "./Button";

const meta = {
  title: "Components/Button",
  component: Button,
  args: { children: "Save changes" },
} satisfies Meta<typeof Button>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Primary: Story = { args: { variant: "primary" } };
export const Secondary: Story = { args: { variant: "secondary" } };
export const Ghost: Story = { args: { variant: "ghost" } };
export const Danger: Story = { args: { variant: "danger", children: "Delete project" } };
export const Small: Story = { args: { size: "sm" } };
export const Loading: Story = { args: { loading: true, children: "Saving changes" } };
export const Disabled: Story = { args: { disabled: true } };

export const WithIcon: Story = {
  render: (args) => (
    <Button {...args}>
      <Plus aria-hidden="true" className="size-4" />
      New dataset
    </Button>
  ),
};

export const AsChildLink: Story = {
  render: (args) => (
    <Button {...args} asChild>
      <a href="#projects">Open projects</a>
    </Button>
  ),
};

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="primary">Save changes</Button>
      <Button variant="secondary">Cancel</Button>
      <Button variant="ghost">Show details</Button>
      <Button variant="danger">Delete project</Button>
      <Button variant="primary" size="sm">
        Save changes
      </Button>
      <Button variant="secondary" size="sm">
        Cancel
      </Button>
      <Button loading>Saving changes</Button>
      <Button disabled>Save changes</Button>
    </div>
  ),
};
