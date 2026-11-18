import type { Config } from "tailwindcss";

// Colours come from CSS variables (app/globals.css) so a new theme only edits tokens.
const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
export default config;
