import type { Meta, StoryObj } from "@storybook/react";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "./Select";

const meta = {
  title: "Components/Select",
  component: Select,
} satisfies Meta<typeof Select>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <div className="w-64">
      <Select defaultValue="duckdb">
        <SelectTrigger aria-label="Engine">
          <SelectValue placeholder="Choose an engine" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Embedded</SelectLabel>
            <SelectItem value="duckdb">DuckDB</SelectItem>
          </SelectGroup>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Pushdown (later)</SelectLabel>
            <SelectItem value="trino" disabled>
              Trino
            </SelectItem>
            <SelectItem value="spark" disabled>
              Spark
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  ),
};

export const Placeholder: Story = {
  render: () => (
    <div className="w-64">
      <Select>
        <SelectTrigger aria-label="Model">
          <SelectValue placeholder="Choose a model" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="gpt">gpt-4.1</SelectItem>
          <SelectItem value="claude">claude-sonnet</SelectItem>
          <SelectItem value="local">llama-3.1-8b (local)</SelectItem>
        </SelectContent>
      </Select>
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <div className="w-64">
      <Select disabled>
        <SelectTrigger aria-label="Engine">
          <SelectValue placeholder="Choose an engine" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="duckdb">DuckDB</SelectItem>
        </SelectContent>
      </Select>
    </div>
  ),
};
