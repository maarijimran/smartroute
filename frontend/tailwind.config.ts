import type { Config } from "tailwindcss";

// Every colour is a CSS variable (see app/globals.css), so the whole interface
// switches between the light and dark themes by changing one attribute.
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;
const scale = (name: string, steps: number[]) => Object.fromEntries(steps.map((s) => [s, v(`${name}-${s}`)]));

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        white: v("white"),
        sidebar: v("sidebar"),
        "sidebar-active": v("sidebar-active"),
        bubble: v("bubble"),
        onbrand: v("onbrand"),
        slate: scale("slate", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        brand: scale("brand", [50, 100, 500, 600, 700]),
        emerald: scale("emerald", [50, 100, 200, 700, 800, 900]),
        amber: scale("amber", [50, 100, 200, 800, 900]),
        red: scale("red", [50, 100, 200, 600, 700, 800, 900]),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        serif: ["ui-serif", "Georgia", "Cambria", "Times New Roman", "Times", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
