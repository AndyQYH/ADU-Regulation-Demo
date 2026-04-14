# Deploy ADU app to Railway (Frontend + Backend)

This repo is set up as two containers:

- `frontend` (Next.js)
- `backend` (FastAPI)

## 1) Push this repo to GitHub

Railway deploys from GitHub, so push your latest code first.

## 2) Verify containers locally (recommended)

From repo root:

```bash
docker compose up --build
```

Then test:

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/docs`

Stop with `Ctrl + C`, then:

```bash
docker compose down
```

## 3) Create Railway project

1. In Railway, click **New Project** -> **Deploy from GitHub repo**.
2. Choose this repo.
3. Create **two services** in the same Railway project:
   - Service A: `backend` (root directory: `backend`)
   - Service B: `frontend` (root directory: `frontend`)
4. For each service, keep **Dockerfile** build mode (Railway will detect each Dockerfile).

## 4) Configure backend service variables

In Railway -> backend service -> Variables:

- Add all required values currently in your local `backend/.env`.
- Set `FRONTEND_ORIGINS` to your Railway frontend domain, for example:
  - `https://your-frontend-name.up.railway.app`

## 5) Configure frontend service variables

In Railway -> frontend service -> Variables:

- `FASTAPI_URL=https://your-backend-name.up.railway.app`
- Optional: `NEXT_PUBLIC_BACKEND_URL=https://your-backend-name.up.railway.app`
- Optional: `NEXT_PUBLIC_CHAT_API_URL=/api/chat`

## 6) Deploy order

1. Deploy backend first.
2. Copy backend public URL.
3. Set `FASTAPI_URL` in frontend.
4. Deploy frontend.

## 7) Validate deployment

- Open frontend domain and run a chat query.
- Open frontend route(s) that depend on regulation sync panels.
- Confirm backend endpoint from internet:
  - `https://<backend-domain>/docs`

## Notes

- Keep secrets only in Railway Variables (do not commit `.env`).
- If CORS errors appear, verify backend `FRONTEND_ORIGINS` exactly matches frontend domain.
- Railway free/trial limits can cause cold starts; paid plans reduce this for demos.
