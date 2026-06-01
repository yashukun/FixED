/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  // Theme is driven by `data-theme` on <html>. `dark:` variants apply in dark
  // mode; the structural `slate` palette below is remapped per-theme via CSS
  // variables (inverted in light mode), so most of the UI flips automatically.
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        background: '#020617',
        panel: '#0f172a',
        accent: '#3b82f6',
        muted: '#94a3b8',
        // The `slate` scale resolves to CSS variables so a single theme switch
        // (light/dark) re-colors every `*-slate-*` utility already in the app.
        slate: {
          50: 'rgb(var(--slate-50) / <alpha-value>)',
          100: 'rgb(var(--slate-100) / <alpha-value>)',
          200: 'rgb(var(--slate-200) / <alpha-value>)',
          300: 'rgb(var(--slate-300) / <alpha-value>)',
          400: 'rgb(var(--slate-400) / <alpha-value>)',
          500: 'rgb(var(--slate-500) / <alpha-value>)',
          600: 'rgb(var(--slate-600) / <alpha-value>)',
          700: 'rgb(var(--slate-700) / <alpha-value>)',
          800: 'rgb(var(--slate-800) / <alpha-value>)',
          900: 'rgb(var(--slate-900) / <alpha-value>)',
          950: 'rgb(var(--slate-950) / <alpha-value>)',
        },
      },
      boxShadow: {
        glow: '0 0 20px rgba(59, 130, 246, 0.25)',
      },
    },
  },
  plugins: [],
}
