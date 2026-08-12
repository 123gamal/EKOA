import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "success" | "warning" | "error" | "info";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  /** Pulses the badge — for in-progress states (PROCESSING, RUNNING, SYNCING). */
  animated?: boolean;
}

const variants: Record<BadgeVariant, string> = {
  default: "bg-[var(--muted)] text-[var(--muted-foreground)] border border-transparent",
  success:
    "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)] border border-[color-mix(in_srgb,var(--success)_35%,transparent)]",
  warning:
    "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-[var(--warning)] border border-[color-mix(in_srgb,var(--warning)_35%,transparent)]",
  error:
    "bg-[color-mix(in_srgb,var(--destructive)_16%,transparent)] text-[var(--destructive)] border border-[color-mix(in_srgb,var(--destructive)_35%,transparent)]",
  info: "bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] text-[var(--primary)] border border-[color-mix(in_srgb,var(--primary)_35%,transparent)]",
};

export function Badge({ className, variant = "default", animated = false, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variants[variant],
        animated && "animate-glow-pulse",
        className
      )}
      {...props}
    />
  );
}

export function statusBadgeVariant(status: string): BadgeVariant {
  switch (status.toUpperCase()) {
    case "INDEXED":
      return "success";
    case "FAILED":
    case "ENQUEUE_FAILED":
      return "error";
    case "PROCESSING":
    case "PENDING":
      return "warning";
    default:
      return "default";
  }
}
