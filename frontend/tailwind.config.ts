import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#151515",
        paper: "#f7f6f2",
        line: "#d9d5ca",
        teal: {
          700: "#0f766e",
          900: "#134e4a",
        },
      },
    },
  },
  plugins: [],
};

export default config;
