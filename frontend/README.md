# frontend — интерфейс

React + TypeScript + Vite: три блока «новости → аналитика → решения», стрелки, матрица рисков, чат. Подробно: [docs/frontend.md](../docs/frontend.md), контракт — [docs/backend.md](../docs/backend.md).

| Путь | Что внутри |
|---|---|
| `src/api` | клиент и типы контракта |
| `src/lib` | кэш, применение патчей, фокус |
| `src/components` | стартовое меню, таймлайн, шапка, доска, виджеты, стрелки, окна |
| `src/styles` | стили |

```bash
npm ci
npm run dev      # http://localhost:5173, /api идёт на 127.0.0.1:8000
npm test && npm run build
```

Оформление: токены `@alfalab/core-components-vars` в `src/styles/base.css`; реклама Альфа-Бизнеса при загрузке — `src/components/widgets/AdTip.tsx` + `src/styles/adtip.css`.
