# HealthGuard AI — React frontend integration

Preserves the original visual design and connects live backend reads for authentication, metrics, RAG, medications, today's doses, agents, notifications, monitoring events, documents and RAG status.

## Install
Copy `src/`, `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html` into `F:\healthcare-ai-agent\frontend`. Keep your existing `.env` and `public/healthguard-logo.png`.

Run `npm install`, `npm run build`, `npm run dev`. FastAPI must be running at `http://127.0.0.1:8000` with CORS configured for the Vite origin.

## Important limitations
Write actions (medication creation, dose confirmation, document upload, agent assessment) are intentionally not enabled because the uploaded material does not include their required OpenAPI request schemas. This package does not pretend these actions are saved. Provide `frontend_api_contract.json` to complete them accurately.

No sensitive data is included. Do not commit `.env` or real medical records.
