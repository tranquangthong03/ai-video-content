import * as React from "react";
import { cn } from "@/lib/utils";

const base =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-50";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(base, "h-10", className)} {...props} />,
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(base, "min-h-[72px] resize-y", className)} {...props} />
));
Textarea.displayName = "Textarea";

export function Checkbox({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn("h-4 w-4 rounded border-border accent-[hsl(var(--primary))]", className)}
      {...props}
    />
  );
}
