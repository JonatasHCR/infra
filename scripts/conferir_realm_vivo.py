"""Compara o realm que esta rodando com o realm-ufc.json versionado.

O Keycloak so importa o JSON quando o realm ainda nao existe. Depois disso, o
arquivo e o que esta no ar podem divergir em silencio — este script mostra onde.

    python scripts/conferir_realm_vivo.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REALM = "ufc"


def ler_env() -> dict:
    valores = {}
    caminho = RAIZ / ".env"
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


def token(base: str, usuario: str, senha: str) -> str:
    dados = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": usuario,
            "password": senha,
        }
    ).encode()
    url = f"{base}/realms/master/protocol/openid-connect/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=dados), timeout=20) as r:
        return json.load(r)["access_token"]


def api(base: str, acesso: str, caminho: str):
    url = f"{base}/admin/realms/{REALM}{caminho}"
    pedido = urllib.request.Request(url, headers={"Authorization": f"Bearer {acesso}"})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return json.load(r)


def main() -> int:
    env = ler_env()
    host = env.get("HOST_IP", "localhost")
    base = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")

    try:
        acesso = token(base, env.get("KC_ADMIN", "admin"), env["KC_ADMIN_PASSWORD"])
    except (urllib.error.URLError, KeyError) as erro:
        print(f"nao consegui autenticar no Keycloak em {base}: {erro}")
        return 1

    esperado = json.loads((RAIZ / "keycloak" / "realm-ufc.json").read_text(encoding="utf-8"))

    print(f"HOST_IP no .env: {host}")
    print(f"issuer no ar:    {api(base, acesso, '')['realm']} @ {base}\n")

    # --- clients -----------------------------------------------------------
    vivos = {c["clientId"]: c for c in api(base, acesso, "/clients")}
    no_arquivo = {c["clientId"]: c for c in esperado["clients"]}

    print("clients:")
    for nome in sorted(set(no_arquivo) | (set(vivos) & set(no_arquivo))):
        vivo = vivos.get(nome)
        if vivo is None:
            print(f"  FALTA     {nome}  (esta no JSON, nao esta no Keycloak)")
            continue
        uris = vivo.get("redirectUris") or []
        erradas = [u for u in uris if host not in u]
        if erradas:
            print(f"  IP ERRADO {nome}  -> {', '.join(erradas)}")
        else:
            print(f"  ok        {nome}  -> {', '.join(uris) or '(sem redirect)'}")

    # --- grupos ------------------------------------------------------------
    print("\ngrupos:")
    grupos = api(base, acesso, "/groups")
    caminhos = set()

    def coletar(lista):
        for grupo in lista:
            caminhos.add(grupo["path"])
            coletar(grupo.get("subGroups") or [])

    coletar(grupos)

    esperados = set()
    for grupo in esperado["groups"]:
        esperados.add(grupo["path"])
        for sub in grupo.get("subGroups") or []:
            esperados.add(sub["path"])

    for caminho in sorted(esperados):
        marca = "ok      " if caminho in caminhos else "FALTA   "
        print(f"  {marca}  {caminho}")

    # --- usuarios ----------------------------------------------------------
    pessoas = api(base, acesso, "/users?max=1000")
    print(f"\nusuarios no realm: {len(pessoas)}")
    for pessoa in pessoas[:20]:
        print(f"  {pessoa.get('email') or pessoa['username']}")
    if len(pessoas) > 20:
        print(f"  ... e mais {len(pessoas) - 20}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
