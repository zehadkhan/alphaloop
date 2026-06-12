import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },

      colors: {
        /* Solid CSS-var colours (no opacity modifier needed) */
        background:       "var(--background)",
        surface:          "var(--surface)",
        "surface-2":      "var(--surface-2)",
        "border-subtle":  "var(--border-subtle)",
        "text-primary":   "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-muted":     "var(--text-muted)",

        /* RGB-tuple colours — supports bg-profit/20, text-loss/50, etc. */
        profit: "rgb(var(--profit) / <alpha-value>)",
        loss:   "rgb(var(--loss)   / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
      },

      animation: {
        "fade-in":   "fadeIn 0.3s ease-in-out",
        "slide-in":  "slideIn 0.3s ease-out",
        "slide-up":  "slideUp 0.35s ease-out",
        "pulse-dot": "pulseDot 1.4s ease-in-out infinite",
        "glow-pulse": "glowPulse 2s ease-in-out infinite",
      },

      keyframes: {
        fadeIn: {
          "0%":   { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideIn: {
          "0%":   { opacity: "0", transform: "translateY(-10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          "0%":   { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseDot: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%":      { opacity: "0.4", transform: "scale(0.75)" },
        },
        glowPulse: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.6" },
        },
      },

      boxShadow: {
        "glow-profit": "0 0 16px rgb(var(--profit) / 0.35), 0 0 40px rgb(var(--profit) / 0.15)",
        "glow-loss":   "0 0 16px rgb(var(--loss)   / 0.35), 0 0 40px rgb(var(--loss)   / 0.15)",
        "glow-accent": "0 0 16px rgb(var(--accent) / 0.35), 0 0 40px rgb(var(--accent) / 0.15)",
      },
    },
  },
  plugins: [],
};

export default config;
