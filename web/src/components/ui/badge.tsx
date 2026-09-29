import type { ComponentProps } from "react";

import { TONE_CLASSES, type Tone } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

export function Badge({ tone = "neutral", className, ...props }: ComponentProps<"span"> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium [&_svg]:size-3.5",
        TONE_CLASSES[tone],
        className,
      )}
      {...props}
    />
  );
}
