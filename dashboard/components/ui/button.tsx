import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-profit/40",
  {
    variants: {
      variant: {
        primary:
          "bg-profit text-black hover:bg-profit/90 active:scale-[0.98] shadow-sm shadow-profit/20 font-semibold",
        danger:
          "bg-loss/90 text-white hover:bg-loss active:scale-[0.98]",
        ghost:
          "bg-white/5 text-text-secondary hover:bg-white/10 hover:text-text-primary border border-white/[0.08]",
        outline:
          "bg-transparent border border-border-subtle text-text-secondary hover:border-profit/60 hover:text-profit hover:bg-profit/5",
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
