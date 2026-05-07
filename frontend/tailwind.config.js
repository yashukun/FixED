/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        background: '#020617',
        panel: '#0f172a',
        accent: '#3b82f6',
        muted: '#94a3b8',
      },
      boxShadow: {
        glow: '0 0 20px rgba(59, 130, 246, 0.25)',
      },
    },
  },
  plugins: [],
}
