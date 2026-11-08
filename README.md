# videoke-cloud

API da nuvem do **Videokê Família Silva** — subconjunto autossuficiente para deploy
(sem o app desktop / PySide6). Extraído do monorepo `karaoke-platform`.

Contém só o necessário para a imagem da nuvem:

- `shared/` — contratos, cliente, eventos (kk-shared)
- `library_core/` — domínio + serviço ASGI/FastAPI + Postgres (kk-core)
- `downloader/` — backend yt-dlp para resolver fontes (kk-downloader)
- `cloud/` — `Dockerfile`, workspace mínimo e docs de deploy
- `render.yaml` — Blueprint do Render (web service Docker, região Ohio)
- `scripts/` — `sync_to_cloud.py` (sincroniza o catálogo) e `smoke_resolve_cloud.py`

## Deploy (Render)

Blueprint lê o `render.yaml`. Variáveis:

- `DATABASE_URL` — Session pooler do Supabase (projeto TOKEN VIDEOKE, usuário `videoke_app`)
- `DB_SCHEMA=videoke` — isola no schema próprio
- `VK_ADMIN_TOKEN` — token admin para o sync

Testar: `GET /health` → `{"ok": true}`. As tabelas sobem no 1º boot (`create_all`).

## Build local

```
docker build -f cloud/Dockerfile -t videoke-cloud .
```

Ver `cloud/DEPLOY.md` para o passo a passo completo.
