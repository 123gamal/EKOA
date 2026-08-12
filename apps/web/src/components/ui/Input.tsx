import { InputHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, id, ...props }, ref) => (
    <div className="space-y-1">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={id}
        className={cn(
          "w-full rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm transition-shadow duration-200 focus:outline-none focus:border-[var(--primary)] focus:shadow-[0_0_0_4px_rgba(var(--glow),0.15)]",
          error && "border-[var(--destructive)]",
          className
        )}
        {...props}
      />
      {error && <p className="text-xs text-[var(--destructive)]">{error}</p>}
    </div>
  )
);
Input.displayName = "Input";
