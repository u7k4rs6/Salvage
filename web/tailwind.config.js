/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // The palette is fixed by docs/04_FRONTEND_SPEC.md section 6: neutral greys for structure,
      // one accent, and red, amber and green reserved for meanings rather than decoration.
      colors: {
        accent: {
          DEFAULT: "#0f766e",
          hover: "#115e59",
          soft: "#ccfbf1",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        table: ["13px", "20px"],
      },
    },
  },
  plugins: [],
};
