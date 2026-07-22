import * as React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { Bot, Database, FileText, Play, Search } from "lucide-react";
import { Button } from "./Button";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "./Command";
import { Kbd } from "./Kbd";

const meta = {
  title: "Components/Command",
  component: Command,
} satisfies Meta<typeof Command>;
export default meta;

type Story = StoryObj<typeof meta>;

function OmnibarContent() {
  return (
    <>
      <CommandInput placeholder="Search objects or type a command" />
      <CommandList>
        <CommandEmpty>Nothing found. Press Enter to ask Copilot.</CommandEmpty>
        <CommandGroup heading="Datasets">
          <CommandItem icon={<Database />} hint="dataset">
            orders_clean
          </CommandItem>
          <CommandItem icon={<Database />} hint="dataset">
            churn_features
          </CommandItem>
        </CommandGroup>
        <CommandGroup heading="Agents">
          <CommandItem icon={<Bot />} hint="agent">
            support-triage
          </CommandItem>
        </CommandGroup>
        <CommandGroup heading="Actions">
          <CommandItem icon={<Play />} hint="⏎">
            Build orders_clean
          </CommandItem>
          <CommandItem icon={<FileText />}>New agent from template</CommandItem>
        </CommandGroup>
      </CommandList>
    </>
  );
}

/** Inline surface — what the ⌘K dialog wraps. */
export const InlineSurface: Story = {
  render: () => (
    <div className="w-[32rem] rounded-lg border border-border shadow-2">
      <Command>
        <OmnibarContent />
      </Command>
    </div>
  ),
};

export const AsOmnibarDialog: Story = {
  render: function AsOmnibarDialogStory() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          <Search aria-hidden="true" className="size-4" />
          Open omnibar
          <Kbd>⌘K</Kbd>
        </Button>
        <CommandDialog open={open} onOpenChange={setOpen}>
          <OmnibarContent />
        </CommandDialog>
      </>
    );
  },
};
