/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        mts: {
          red: '#E30611',
          dark: '#B30510',
          light: '#FDECEE',
        },
      },
    },
  },
  plugins: [],
};
