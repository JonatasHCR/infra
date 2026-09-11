"""Aplica no Keycloak em execucao o que o realm-ufc.json ganhou depois do boot.

O Keycloak importa o realm UMA vez, no primeiro boot. Depois disso, acrescentar
um sistema ao JSON nao muda nada no que esta no ar, e `down -v` resolveria a
custo de apagar todos os usuarios e associacoes de grupo.

Este script fecha essa lacuna: cria os grupos e clients que faltam e corrige os
redirect URIs divergentes, sem tocar em usuario nenhum. E idempotente.

    python scripts/aplicar_realm.py            # mostra o que faria
    python scripts/aplicar_realm.py --apply    # aplica
"""

from __future__ import annotations

import os
import sys
import urllib.error

from keycloak_admin import Keycloak, ler_env, realm_versionado, renderizar


def main() -> int:
    aplicar = "--apply" in sys.argv
    env = ler_env()
    base = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")

    try:
        kc = Keycloak(base, env.get("KC_ADMIN", "admin"), env["KC_ADMIN_PASSWORD"])
    except (urllib.error.URLError, KeyError) as erro:
        print(f"nao consegui autenticar no Keycloak em {base}: {erro}")
        print("o Keycloak esta no ar? (cd infra && docker compose up -d keycloak)")
        return 1

    desejado = renderizar(realm_versionado(), env)
    pendencias = []

    # --- grupos ------------------------------------------------------------
    grupos = kc.grupos_com_filhos()

    for grupo in desejado["groups"]:
        if grupo["path"] not in grupos:
            pendencias.append(("grupo", grupo["path"], None))
            continue
        for sub in grupo.get("subGroups") or []:
            if sub["path"] not in grupos:
                pendencias.append(("subgrupo", sub["path"], grupos[grupo["path"]]))

    # --- clients -----------------------------------------------------------
    vivos = kc.clients()
    for client in desejado["clients"]:
        nome = client["clientId"]
        vivo = vivos.get(nome)
        if vivo is None:
            pendencias.append(("client", nome, client))
            continue
        # O `name` e visivel: e o rotulo do "voltar" no Account Console.
        if (
            sorted(vivo.get("redirectUris") or []) != sorted(client.get("redirectUris") or [])
            or vivo.get("name") != client.get("name")
        ):
            pendencias.append(("redirect", nome, (vivo, client)))

    if not pendencias:
        print("o Keycloak ja esta igual ao realm-ufc.json")
        return 0

    print(f"{len(pendencias)} pendencia(s):\n")
    for tipo, nome, _ in pendencias:
        print(f"  {tipo:9} {nome}")

    if not aplicar:
        print("\n(nada foi alterado; rode com --apply)")
        return 0

    print()
    for tipo, nome, extra in pendencias:
        if tipo == "grupo":
            kc.post("/groups", {"name": nome.strip("/")})
            print(f"  criado grupo {nome}")
        elif tipo == "subgrupo":
            kc.post(f"/groups/{extra}/children", {"name": nome.rsplit("/", 1)[-1]})
            print(f"  criado subgrupo {nome}")
        elif tipo == "client":
            corpo = dict(extra)
            # protocolMappers entram junto na criacao.
            kc.post("/clients", corpo)
            print(f"  criado client {nome}")
        elif tipo == "redirect":
            vivo, querido = extra
            atualizado = dict(vivo)
            atualizado["redirectUris"] = querido.get("redirectUris") or []
            atualizado["webOrigins"] = querido.get("webOrigins") or []
            atualizado["name"] = querido.get("name")
            kc.put(f"/clients/{vivo['id']}", atualizado)
            print(f"  corrigidos redirect URIs / nome de {nome}")

    print("\npronto. Confira com: python scripts/conferir_realm_vivo.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
