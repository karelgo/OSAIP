import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "./Button";
import {
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "./Dialog";

const meta = {
  title: "Components/Dialog",
  component: Dialog,
} satisfies Meta<typeof Dialog>;
export default meta;

type Story = StoryObj<typeof meta>;

export const Basic: Story = {
  render: () => (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="secondary">Show session details</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Session details</DialogTitle>
          <DialogDescription>
            Modals are reserved for destructive confirmation — configuration belongs in the
            inspector. This story exists to show the surface itself.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="secondary">Close</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ),
};

/** The sanctioned modal: destructive confirmation (§6.3(2)). */
export const DestructiveConfirm: Story = {
  render: () => (
    <ConfirmDialog
      title="Delete dataset?"
      description="orders_raw and its 3 versions will be removed. Downstream recipes will fail until they are repointed."
      confirmLabel="Delete dataset"
      destructive
      onConfirm={() => new Promise((resolve) => setTimeout(resolve, 800))}
      trigger={<Button variant="danger">Delete dataset</Button>}
    />
  ),
};

export const NonDestructiveConfirm: Story = {
  render: () => (
    <ConfirmDialog
      title="Rebuild all downstream datasets?"
      description="14 datasets are stale and will rebuild now."
      confirmLabel="Rebuild 14 datasets"
      onConfirm={() => undefined}
      trigger={<Button variant="secondary">Rebuild downstream</Button>}
    />
  ),
};
