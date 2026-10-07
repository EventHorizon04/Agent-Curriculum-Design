# Curriculum Design Agent — frontend

## Mock mode (no backend)

```bash
npm run dev:mock    # vite --mode mock --port 5174 --strictPort
```

Opens the whole UI on http://localhost:5174 with every API call answered in the
browser by `src/mock/` — a click-through of every stage, every PLO verdict state
and the Pipeline session flow, without touching a backend or a database.

**The guarantee.** In `mock` mode `vite.config.ts` has no `server.proxy`, so even a
call the mock failed to intercept 404s on the dev server; it cannot reach the real
API on :8000. Port 5174 is a different origin from the real app on :5173, so the
two never share localStorage (the selected program). The mock code is loaded
through a dynamic import behind `import.meta.env.MODE === 'mock'`, and a normal
`npm run build` contains none of it.

**Scenarios** — pick one in the yellow `MOCK` panel (bottom-right) and press
"รีเซ็ต", or load a URL with `?mock=<name>` to seed and select on load (the
parameter is then removed, so a reload keeps what you have done since):

| name         | what it seeds |
| ------------ | ------------- |
| `empty`      | no programs at all |
| `checkpoint` | one fictional translation programme: 8 evidence items, 28 skills, 12 Needs (optional, a `[ต้องทบทวน]` fallback, two held back by the scope guard), a session suspended at the shared skill/Need checkpoint, no PLOs |
| `complete`   | the same plus 8 core PLOs and OPT1 covering every verdict state (agent pass, escalated with a hard finding, soft findings, `stale`, `code_only`, `legacy`), three unused Needs, a completed session |
| `many`       | four programs at different stages and session states, for the program list |

e.g. http://localhost:5174/plo-report?mock=complete

The panel also turns simulated latency off, makes the next API request answer
500, and makes the next run (a stage's Run button, or the next step of a Pipeline
session) fail. State lives in sessionStorage: it survives a reload and is gone
when the tab closes. All data is invented.

## Vite template notes

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
