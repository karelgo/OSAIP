// Placeholder for modules that ship in a later phase — still a designed empty state
// with a starting point (§6.3(9), §6.7), never a dead end.
import { EmptyState } from "@osaip/ui";
import { Hourglass } from "lucide-react";

export function StubPage({ title, phase }: { title: string; phase: number }) {
  return (
    <div className="flex h-full items-center justify-center p-8" data-testid="stub-page">
      <EmptyState
        icon={<Hourglass aria-hidden className="size-8" />}
        title={`${title} arrives in phase ${phase}`}
        description="This part of OSAIP is on the roadmap. The navigation is already in place so you can learn the layout once."
      />
    </div>
  );
}
