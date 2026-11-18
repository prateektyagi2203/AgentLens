import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        rust: { 50: "#fdf5f0", 600: "#b9532c", 700: "#9c4222", 800: "#7f351b" },
      },
    },
  },
  plugins: [],
};
export default config;
