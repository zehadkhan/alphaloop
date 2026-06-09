import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0f1117",
        surface: "#151823",
        "surface-2": "#1a1f2e",
        "border-subtle": "#1e2433",
        profit: "#00c076",
        loss: "#ff3b69",
        "profit-dim": "#00c07620",
        "loss-dim": "#ff3b6920",
        accent: "#3b82f6",
        "accent-dim": "#3b82f620",
        "text-primary": "#e2e8f0",
        "text-secondary": "#94a3b8",
        "text-muted": "#4b5675",
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      animation: {
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-in-out",
        "slide-in": "slideIn 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideIn: {
          "0%": { opacity: "0", transform: "translateY(-8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
