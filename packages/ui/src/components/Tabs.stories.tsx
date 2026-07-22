import type { Meta, StoryObj } from "@storybook/react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./Tabs";

const meta = {
  title: "Components/Tabs",
  component: Tabs,
} satisfies Meta<typeof Tabs>;
export default meta;

type Story = StoryObj<typeof meta>;

/** The canonical inspector tab order (§6.3(2)). */
export const InspectorPattern: Story = {
  render: () => (
    <Tabs defaultValue="configure" className="w-[28rem]">
      <TabsList>
        <TabsTrigger value="configure">Configure</TabsTrigger>
        <TabsTrigger value="preview">Preview</TabsTrigger>
        <TabsTrigger value="runs">Runs</TabsTrigger>
        <TabsTrigger value="lineage">Lineage</TabsTrigger>
        <TabsTrigger value="docs">Docs</TabsTrigger>
      </TabsList>
      <TabsContent value="configure" className="text-sm text-muted">
        Recipe parameters live here; edits preview instantly on a sample.
      </TabsContent>
      <TabsContent value="preview" className="text-sm text-muted">
        1k-row DuckDB sample preview.
      </TabsContent>
      <TabsContent value="runs" className="text-sm text-muted">
        Past builds with status and duration.
      </TabsContent>
      <TabsContent value="lineage" className="text-sm text-muted">
        Upstream and downstream datasets.
      </TabsContent>
      <TabsContent value="docs" className="text-sm text-muted">
        Descriptions and glossary links.
      </TabsContent>
    </Tabs>
  ),
};

export const WithDisabledTab: Story = {
  render: () => (
    <Tabs defaultValue="configure" className="w-96">
      <TabsList>
        <TabsTrigger value="configure">Configure</TabsTrigger>
        <TabsTrigger value="preview" disabled>
          Preview
        </TabsTrigger>
      </TabsList>
      <TabsContent value="configure" className="text-sm text-muted">
        Preview unlocks after the first build.
      </TabsContent>
    </Tabs>
  ),
};
