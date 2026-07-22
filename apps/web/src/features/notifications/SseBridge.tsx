import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { startEventStream } from "./sse";

export function SseBridge() {
  const queryClient = useQueryClient();
  useEffect(() => startEventStream(queryClient), [queryClient]);
  return null;
}
