import type { Meta, StoryObj } from "@storybook/react";
import { Field, Input } from "./Input";

const meta = {
  title: "Components/Input",
  component: Input,
} satisfies Meta<typeof Input>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { placeholder: "Search datasets" },
  render: (args) => (
    <div className="w-72">
      <Input {...args} />
    </div>
  ),
};

export const Disabled: Story = {
  args: { placeholder: "Search datasets", disabled: true },
  render: (args) => (
    <div className="w-72">
      <Input {...args} />
    </div>
  ),
};

export const WithField: Story = {
  render: () => (
    <div className="w-72">
      <Field label="Project name" hint="Shown in the project switcher.">
        <Input placeholder="Customer churn" />
      </Field>
    </div>
  ),
};

export const WithError: Story = {
  render: () => (
    <div className="w-72">
      <Field label="Project key" error="Use lowercase letters and dashes only.">
        <Input defaultValue="My Project!" />
      </Field>
    </div>
  ),
};
