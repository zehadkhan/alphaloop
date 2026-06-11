import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        /* Solid CSS-var colours (no opacity modifier needed) */
        background:      "var(--background)",
        surface:         "var(--surface)",
        "surface-2":     "var(--surface-2)",
        "border-subtle": "var(--border-subtle)",
        "text-primary":   "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-muted":     "var(--text-muted)",

        /* RGB-tuple colours — supports bg-profit/20, text-loss/50, etc. */
        profit: "rgb(var(--profit) / <alpha-value>)",
        loss:   "rgb(var(--loss)   / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
      },
      animation: {
        "fade-in":  "fadeIn 0.3s ease-in-out",
        "slide-in": "slideIn 0.3s ease-out",
      },
      keyframes: {
        fadeIn:  { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideIn: { "0%": { opacity: "0", transform: "translateY(-8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};

export default config;
