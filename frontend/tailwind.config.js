/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        // Royal blue accent
        primary: {
          50: '#eef3ff',
          100: '#dde6ff',
          200: '#c2d2ff',
          300: '#97b2ff',
          400: '#6489ff',
          500: '#3d66ff',
          600: '#2a53f0',
          700: '#2142d0',
          800: '#2038a6',
          900: '#203482',
        },
        // App canvas behind the white cards
        canvas: '#f3f4f8',
      },
      borderRadius: {
        card: '1.25rem',
      },
    },
  },
  plugins: [],
}
