# Deploy da nuvem do Videokê (API + sync)

A API (`cloud/Dockerfile`) já foi validada localmente: builda e serve o catálogo
sobre Postgres. Falta só ligar nas suas contas. Passo a passo:

## 1. Postgres (Supabase) — pode ser o MESMO do Mês Redondo
Não precisa de outra instância: o Videokê fica num **schema próprio** (`videoke`),
isolado do Mês Redondo (que fica em `public`). Você paga só o Supabase que já tem.
1. Use o Supabase que já tem (ou um novo).
2. Use o **POOLER** (IPv4 — a conexão direta `db.xxx.supabase.co` é IPv6-only e o
   Render NÃO alcança). Formato (Session mode, porta **5432**):
   `postgresql://videoke_app.<ref>:<senha>@aws-0-<regiao>.pooler.supabase.com:5432/postgres`
   (a API normaliza `postgresql://` → `postgresql+psycopg://` sozinha. Session mode
   evita o problema de prepared statements do modo transação/6543.)
3. **Usuário dedicado `videoke_app`** (criado via Management API), com permissão
   SÓ no schema `videoke` — a API não consegue ler/escrever nas tabelas do Mês
   Redondo (`public`). O schema `videoke` + 29 tabelas já estão criados.

## 2. API (Render)
1. Render → **New → Blueprint** → aponte para este repo, branch `videoke-mobile`
   (ele lê `cloud/render.yaml`).
2. Em **Environment**:
   - `DATABASE_URL` = a connection string do Supabase (passo 1).
   - `VK_ADMIN_TOKEN` = deixe gerar (ou defina) e **copie** — é o token do sync.
3. Deploy. Teste: `https://SEU-APP.onrender.com/health` → `{"ok":true}`.

> As tabelas são criadas sozinhas no 1º boot (create_all + songs_search).

## 3. Sincronizar o acervo (Desktop → Cloud)
No Mac, com a API no ar:
```
CLOUD_URL=https://SEU-APP.onrender.com \
VK_ADMIN_TOKEN=<o token do Render> \
uv run python scripts/sync_to_cloud.py
```
Envia o catálogo leve (Song + metadados + URLs) em lotes, com cursor retomável.
**Não envia MP4.** Reexecute quando baixar músicas novas (sync incremental).

## 4. Testar
```
curl -s -X POST https://SEU-APP.onrender.com/rpc \
  -H "Content-Type: application/json" \
  -d '{"method":"search_songs","params":{"query":"evidencias"}}'
```

## Pendente (próxima etapa)
- **F4**: apontar o app mobile para a `CLOUD_URL` (token de convidado).
- **G**: servir a reprodução pela nuvem (`/resolve` já existe; falta o proxy de
  streaming e o hot-cache das favoritas) + avaliar o bloqueio do YouTube em
  datacenter (mitigação = hot-cache).
