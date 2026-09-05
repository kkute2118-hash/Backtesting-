import type { Config } from "tailwindcss";

/**
 * The design system lives in CSS custom properties (see globals.css) and is
 * surfaced to Tailwind here. Colours are declared once, in one place, so a
 * "positive" number is the same green on a table row, a KPI tile and a chart —
 * and so the light and dark themes swap by redefining variables rather than by
 * sprinkling `dark:` variants through every component.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "hsl(var(--canvas) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        elevated: "hsl(var(--elevated) / <alpha-value>)",
        line: "hsl(var(--line) / <alpha-value>)",
        strongline: "hsl(var(--strong-line) / <alpha-value>)",
        ink: "hsl(var(--ink) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        faint: "hsl(var(--faint) / <alpha-value>)",
        accent: "hsl(var(--accent) / <alpha-value>)",
        "accent-soft": "hsl(var(--accent-soft) / <alpha-value>)",
        up: "hsl(var(--up) / <alpha-value>)",
        "up-soft": "hsl(var(--up-soft) / <alpha-value>)",
        down: "hsl(var(--down) / <alpha-value>)",
        "down-soft": "hsl(var(--down-soft) / <alpha-value>)",
        warn: "hsl(var(--warn) / <alpha-value>)",
        "warn-soft": "hsl(var(--warn-soft) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        card: "0.625rem",
      },
      boxShadow: {
        card: "0 1px 2px hsl(var(--shadow) / 0.06), 0 1px 3px hsl(var(--shadow) / 0.04)",
        pop: "0 8px 24px hsl(var(--shadow) / 0.14), 0 2px 6px hsl(var(--shadow) / 0.08)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        "fade-in": "fade-in 140ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
