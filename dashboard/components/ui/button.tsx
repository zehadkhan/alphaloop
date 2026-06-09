import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-all duration-150 disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-profit/50",
  {
    variants: {
      variant: {
        primary:
          "bg-profit text-black hover:bg-profit/90 active:scale-95 shadow-lg shadow-profit/20",
        danger:
          "bg-loss text-white hover:bg-loss/90 active:scale-95 shadow-lg shadow-loss/20",
        ghost:
          "bg-transparent text-text-secondary hover:bg-surface-2 hover:text-text-primary border border-border-subtle",
        outline:
          "bg-transparent border border-border-subtle text-text-secondary hover:border-profit/50 hover:text-profit",
      },
      size: {
        sm: "h-7 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-11 px-6 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);

type ButtonVariant = VariantProps<typeof buttonVariants>;

export function Button({
  variant,
  size,
  className,
  children,
  ...props
}: ButtonVariant & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    >
      {children}
    </button>
  );
}
