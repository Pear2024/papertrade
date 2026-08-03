import { cn } from "@/lib/utils";

function Alert({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "warning" | "destructive" }) {
  return (
    <div
      role="alert"
      className={cn(
        "relative w-full rounded-md border px-4 py-3 text-sm",
        variant === "default" && "bg-muted/40 text-foreground",
        variant === "warning" && "border-warning/40 bg-warning/10 text-foreground",
        variant === "destructive" && "border-destructive/40 bg-destructive/10 text-foreground",
        className,
      )}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h5 className={cn("mb-1 font-medium leading-none tracking-tight", className)} {...props} />;
}

function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <div className={cn("text-sm text-muted-foreground [&_p]:leading-relaxed", className)} {...props} />;
}

export { Alert, AlertTitle, AlertDescription };
