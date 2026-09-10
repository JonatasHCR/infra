#!/usr/bin/env python3
"""Cria (ou acerta) a conta mestra do realm ufc — a que administra os tres
sistemas com um login so.

Por que um script e nao o realm-ufc.json:

  1. O `--import-realm` so roda quando o realm AINDA NAO EXISTE.  Numa producao
     ja no ar, semear o usuario no JSON nao faria absolutamente nada.
  2. A senha e escolhida por gente.  O render do realm substitui placeholders
     com `sed`, que trata `&`, `|` e `\\` como especiais no lado direito — uma
     senha com qualquer um deles entraria no realm trocada por outra coisa, e o
     login falharia sem explicacao.  Pela Admin API a senha viaja em JSON, sem
     nenhuma camada de escape no meio.

E idempotente: rodar de novo em cima de uma conta que ja existe apenas
reconfirma grupos e senha.  Nao mexe em nenhuma outra conta.

O que esta conta e:  a MESMA pessoa sendo admin do inventario, da despesa e da
receita.  Os tres backends a reconhecem pelo email, comparado com
ADMIN_MESTRE_EMAIL do .env de cada um.

O que esta conta NAO e:  um papel do Keycloak.  Ser admin do console (KC_ADMIN,
realm master) nao da poder nenhum dentro dos sistemas, e nenhum grupo concede
isso — o unico endereco privilegiado e o que esta no .env.

Uso:
    python scripts/criar_admin_mestre.py            # mostra o que faria
    python scripts/criar_admin_mestre.py --apply    # cria/acerta de fato
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Reaproveita o cliente da Admin API que o import_users ja tem — inclusive a
# reautenticacao no 401, porque o token do admin-cli dura cerca de um minuto.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_users import REALM, Keycloak, ler_env  # noqa: E402

INFRA = Path(__file__).resolve().parent.parent

# A conta mestra dispensa os `/apps/*` para ENTRAR, mas o portal filtra os
# cartoes so por grupo: sem eles a tela inicial fica vazia para quem pode tudo.
GRUPOS = [
    "/admins",
    "/apps/inventario",
    "/apps/receita",
    "/apps/despesa",
    "/apps/controle-despesa",
]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--apply", action="store_true", help="grava de fato (sem isso, so mostra)"
    )
    args = p.parse_args()

    env = ler_env(INFRA / ".env")
    host_ip = env.get("HOST_IP")
    email = (env.get("ADMIN_MESTRE_EMAIL") or "").strip().lower()
    senha = env.get("ADMIN_MESTRE_SENHA") or ""

    if not host_ip:
        sys.exit("ERRO: HOST_IP nao definido em infra/.env.")
    if not email:
        sys.exit(
            "ERRO: ADMIN_MESTRE_EMAIL vazio em infra/.env.\n"
            "      Sem ele nao ha conta mestra — e os tres sistemas continuam\n"
            "      dependendo de promover um admin em cada um pela linha de comando."
        )
    if not senha:
        sys.exit("ERRO: ADMIN_MESTRE_SENHA vazia em infra/.env.")
    if len(senha) < 12:
        sys.exit(
            f"ERRO: ADMIN_MESTRE_SENHA tem {len(senha)} caracteres.\n"
            "      Esta conta administra os tres sistemas de uma vez; use ao menos 12."
        )

    base = f"http://{host_ip}:8080"
    print(f"Keycloak : {base}  (realm {REALM})")
    print(f"Conta    : {email}")
    print(f"Grupos   : {', '.join(GRUPOS)}")

    if not args.apply:
        print("\n--- simulacao. Rode com --apply para gravar. ---")
        return 0

    kc = Keycloak(base, env["KC_ADMIN"], env["KC_ADMIN_PASSWORD"])

    usuario_id = kc.buscar_usuario(email)
    if usuario_id:
        print("\n  conta ja existe — reconfirmando grupos e senha")
    else:
        kc._requisicao("POST", f"/admin/realms/{REALM}/users", {
            "username": email,
            "email": email,
            "firstName": "Administrador",
            "lastName": "Geral",
            "enabled": True,
            "emailVerified": True,
        })
        usuario_id = kc.buscar_usuario(email)
        if not usuario_id:
            sys.exit("ERRO: criei a conta mas nao consegui rele-la.")
        print("\n  conta criada")

    # Senha definitiva, nao temporaria: quem opera o servidor escolheu este
    # valor no .env de proposito.  Um UPDATE_PASSWORD aqui obrigaria a trocar no
    # primeiro login e o .env passaria a mentir sobre a senha real.
    kc._requisicao(
        "PUT", f"/admin/realms/{REALM}/users/{usuario_id}/reset-password",
        {"type": "password", "value": senha, "temporary": False},
    )
    print("  senha definida")

    mapa = kc.grupos()
    for caminho in GRUPOS:
        gid = mapa.get(caminho)
        if not gid:
            print(f"  AVISO: grupo {caminho} nao existe no realm — pulado")
            continue
        kc.associar_grupo(usuario_id, gid)
        print(f"  grupo {caminho}")

    print(
        "\nPronto. Entre pelo portal com esse email.\n"
        "Os sistemas so reconhecem a conta depois que ADMIN_MESTRE_EMAIL\n"
        "estiver no .env de cada um — rode `python scripts/sync_host_ip.py`\n"
        "e recrie os containers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
