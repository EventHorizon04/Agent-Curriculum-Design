import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // Every stage page fetches on mount via an async useCallback that sets
      // loading/error state; the rule cannot see past the first await and
      // flags all of them. The pattern matches React's documented
      // fetch-in-effect usage, so the rule is disabled project-wide.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
