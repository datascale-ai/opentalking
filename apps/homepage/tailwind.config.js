/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1e1b4b",
        mist: "#fbfaff",
        cyanline: "#6366f1",
        mintline: "#fb7185",
        ember: "#f59e0b",
      },
      boxShadow: {
        panel: "0 18px 50px rgba(79, 70, 229, 0.12)",
      },
      keyframes: {
        floatPanel: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        pulseLine: {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "float-panel": "floatPanel 6s ease-in-out infinite",
        "pulse-line": "pulseLine 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
