"use client";

import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ThemeToggle() {
  const [dark, setDark] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("alphaloop-theme", next ? "dark" : "light");
    } catch {}
  }

  /* Avoid hydration mismatch — render a placeholder until mounted */
  if (!mounted) {
    return <div className="h-9 w-9 rounded-lg bg-surface-2 border border-border-subtle" />;
  }

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      className={cn(
        "flex items-center justify-center h-9 w-9 rounded-lg border transition-all duration-150",
        "border-border-subtle bg-surface-2 hover:border-profit/40",
        "text-text-secondary hover:text-text-primary"
      )}
    >
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
