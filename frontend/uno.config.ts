import { defineConfig, presetAttributify, presetIcons, presetUno } from 'unocss'

export default defineConfig({
  presets: [presetUno(), presetAttributify(), presetIcons()],
  theme: {
    colors: {
      openai: {
        50: '#f0fdf4',
        100: '#dcfce7',
        200: '#bbf7d0',
        300: '#86efac',
        400: '#4ade80',
        500: '#10a37f', // Signature OpenAI Emerald
        600: '#0e8c6d',
        700: '#0b7359',
        800: '#095d48',
        900: '#064737',
      },
    },
    fontFamily: {
      sans: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      mono: '"JetBrains Mono", "SF Mono", Menlo, Consolas, monospace',
    },
    boxShadow: {
      'openai-input': '0 0 24px rgba(0, 0, 0, 0.06), 0 2px 6px rgba(0, 0, 0, 0.04)',
      'openai-card': '0 1px 2px 0 rgba(0, 0, 0, 0.04)',
      'openai-card-hover': '0 4px 16px 0 rgba(0, 0, 0, 0.08)',
      'openai-dropdown': '0 10px 38px -10px rgba(22, 23, 24, 0.35), 0 10px 20px -15px rgba(22, 23, 24, 0.2)',
    },
  },
  shortcuts: {
    'openai-btn-primary': 'bg-zinc-900 hover:bg-zinc-800 text-white rounded-full px-4 py-2 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
    'openai-btn-secondary': 'bg-white hover:bg-zinc-50 border border-zinc-200 text-zinc-700 rounded-full px-4 py-2 text-sm font-medium transition-colors shadow-xs',
    'openai-badge': 'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-100 text-zinc-700 border border-zinc-200/60',
    'openai-card-base': 'bg-white border border-zinc-200 rounded-2xl transition-all duration-200',
  },
})

