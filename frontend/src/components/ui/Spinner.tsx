import { LoaderCircle } from "lucide-react";
import { cn } from "../../lib/cn";

export function Spinner({ className, label = "Cargando" }: { className?: string; label?: string }) {
  return (
    <LoaderCircle
      role="status"
      aria-label={label}
      className={cn("size-4 animate-spin text-muted", className)}
    />
  );
}
