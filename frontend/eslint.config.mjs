import antfu from '@antfu/eslint-config'

export default antfu({
  vue: true,
  typescript: true,
  unocss: false,
  formatters: false,
  ignores: ['dist/**', 'node_modules/**', '**/*.md'],
  rules: {
    'no-console': 'off',
    'unused-imports/no-unused-vars': 'off',
    'vue/multi-word-component-names': 'off',
    'ts/explicit-function-return-type': 'off',
    'node/prefer-global/process': 'off',
  },
})
