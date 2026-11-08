"""Configuração do licenciamento — valores públicos (podem ir no binário).

- PUBLIC_KEY_B64: chave pública Ed25519 que VERIFICA o token assinado pelo servidor.
  A privada correspondente fica SÓ no Supabase (segredo LICENSE_PRIVATE_KEY).
- SUPABASE_URL / SUPABASE_ANON_KEY: endpoint da Edge Function `ativar`. A anon key é
  pública por design (protegida por RLS + service_role dentro da função).
- GRACE_DAYS: validade do token; o app funciona offline até vencer, renovando quando online.
"""
from __future__ import annotations

# Chave pública Ed25519 (base64 de 32 bytes). Gerada em licensing/keys/public_key.b64.
PUBLIC_KEY_B64 = "UgL9sVEqv0DhUMLRxDhUyr8eCkqNGXP16Ya3nZf/OzA="

# Projeto Supabase "TOKEN VIDEOKE" (licenciamento do Karaokê)
SUPABASE_URL = "https://xydvxmrusrxcnvzhqzct.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh5ZHZ4bXJ1c3J4Y252emhxemN0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2MTYwODcsImV4cCI6MjEwMTE5MjA4N30."
    "qdzzojDijmCqxPbuCEp5eCUaQUaKDZhxkFSef3qTDB0"
)

GRACE_DAYS = 30              # validade do token; renova sozinho quando online
RENEW_BEFORE_DAYS = 20       # renova em silêncio quando faltar <= isto p/ vencer
