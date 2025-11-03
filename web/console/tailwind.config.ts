import type { Config } from "tailwindcss";

// Design tokens transcribed from design/styles.css
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0A0A0A", 2: "#2A2A2A" },
        muted: { DEFAULT: "#6E6E6E", 2: "#9A9A9A" },
        surface: { DEFAULT: "#FFFFFF", 2: "#F6F6F6", 3: "#EFEFEF" },
        border: { DEFAULT: "#E5E5E5", strong: "#D0D0D0" },
        primary: { 100: "#FAF7AB", 200: "#F6F079", 300: "#F1E94B", 400: "#EDE52E", 500: "#E5DD17", 700: "#87820D" },
        ok: { 100: "#E5EAE7", 500: "#7A857F", 700: "#3D4742" },
        info: { 100: "#DDE9F7", 500: "#3D7DCB", 700: "#1F548E" },
        warn: { 100: "#FBE5C8", 500: "#D98A2B", 700: "#8C5612" },
        err: { 100: "#F8DAD5", 500: "#D85546", 700: "#8B2A20" },
      },
      fontFamily: {
        ui: ['"Plus Jakarta Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "Menlo", "monospace"],
      },
      borderRadius: { pill: "999px" },
    },
  },
  plugins: [],
} satisfies Config;
