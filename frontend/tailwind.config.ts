import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        serif: ["var(--font-serif)", "ui-serif", "Georgia"],
      },
      colors: {
        ink: {
          50: "#f6f4f1",
          100: "#ebe6de",
          200: "#d8d0c3",
          300: "#bdb3a3",
          400: "#8f8576",
          500: "#6f675c",
          600: "#524c44",
          700: "#3c3832",
          800: "#2a2723",
          900: "#1c1a17",
        },
        moss: {
          500: "#3f6b4e",
          600: "#345841",
        },
        rust: {
          500: "#b4533a",
        },
      },
    },
  },
  plugins: [],
};

export default config;
