/** @type {import('tailwindcss').Config} */
// Design-language renewal (SOT-1019). Soft nursery brand: friendly rounded type,
// calm teal brand + warm coral accent, larger radii. Tokens are CSS vars in
// src/index.css so light/dark swap together (bg-brand, bg-surface, shadow-card…).
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Nunito', '"Noto Sans JP"', 'system-ui', '-apple-system', 'sans-serif'],
      },
      colors: {
        brand: 'var(--brand)',
        'brand-strong': 'var(--brand-strong)',
        'brand-soft': 'var(--brand-soft)',
        accent: 'var(--accent)',
        'accent-bg': 'var(--accent-bg)',
        'accent-border': 'var(--accent-border)',
        foreground: 'var(--foreground)',
        'muted-foreground': 'var(--muted-foreground)',
        surface: 'var(--surface)',
        'surface-muted': 'var(--surface-muted)',
        border: 'var(--border)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
      },
      borderRadius: {
        xl2: '1.25rem',
      },
    },
  },
  plugins: [],
}
