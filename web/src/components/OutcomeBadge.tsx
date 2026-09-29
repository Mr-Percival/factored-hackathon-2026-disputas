import { Badge } from "@/components/ui/badge";
import { outcomeMeta } from "@/lib/outcomes";

export function OutcomeBadge({
  outcome,
  className,
}: {
  outcome: string | null | undefined;
  className?: string;
}) {
  const meta = outcomeMeta(outcome);
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} className={className} title={meta.description}>
      <Icon aria-hidden="true" />
      <span>
        <span className="sr-only">Resultado: </span>
        {meta.label}
      </span>
    </Badge>
  );
}
