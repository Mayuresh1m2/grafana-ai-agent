/* eslint-env node */
'use strict'

module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:vue/vue3-recommended',
  ],
  parser: 'vue-eslint-parser',
  parserOptions: {
    parser: '@typescript-eslint/parser',
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint'],
  rules: {
    // Disallow any — enforce type-safe code
    '@typescript-eslint/no-explicit-any': 'error',

    // Consistent return types on exported functions
    '@typescript-eslint/explicit-function-return-type': [
      'warn',
      { allowExpressions: true, allowTypedFunctionExpressions: true },
    ],

    // Unused vars should be errors, but allow _-prefixed intentional ignores
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],

    // Enforce <script setup> style
    'vue/component-api-style': ['error', ['script-setup']],

    // Enforce type-based props
    'vue/define-props-declaration': ['error', 'type-based'],

    // Consistent component naming
    'vue/component-name-in-template-casing': ['error', 'PascalCase'],

    // No v-html — XSS risk
    'vue/no-v-html': 'error',
  },
}
