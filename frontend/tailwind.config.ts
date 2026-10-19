import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { lab: '#0A0B0A', lime: '#B7F774', amber: '#F3BE69' } } },
  plugins: [typography],
} satisfies Config;
