import type { Meta, StoryObj } from "@storybook/react";
import { Copy, Pencil, Play, Trash2 } from "lucide-react";
import { Button } from "./Button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./DropdownMenu";

const meta = {
  title: "Components/DropdownMenu",
  component: DropdownMenu,
} satisfies Meta<typeof DropdownMenu>;
export default meta;

type Story = StoryObj<typeof meta>;

export const WithIconsAndHints: Story = {
  render: () => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary">Dataset actions</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>orders_clean</DropdownMenuLabel>
        <DropdownMenuItem icon={<Play />} hint="B">
          Build dataset
        </DropdownMenuItem>
        <DropdownMenuItem icon={<Pencil />} hint="E">
          Edit recipe
        </DropdownMenuItem>
        <DropdownMenuItem icon={<Copy />}>Duplicate</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem icon={<Trash2 />} className="text-status-danger">
          Delete dataset
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  ),
};

export const WithDisabledItem: Story = {
  render: () => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost">More actions</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem>Open in Flow</DropdownMenuItem>
        <DropdownMenuItem disabled>Promote to production</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  ),
};
