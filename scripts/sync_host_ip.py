#!/usr/bin/env python3
"""Propaga a configuracao compartilhada do infra/.env para os tres projetos.

Os composes sao separados por projeto, e `env_file:` define variavel DENTRO do
container — nao serve para a interpolacao do compose, que so le o `.env` do
diretorio dele.  Entao varios valores precisam mesmo se repetir nos quatro
arquivos, e mante-los iguais a mao e so questao de tempo ate divergirem.

O `infra/.env` e a fonte da verdade.  Este script copia de la para os outros.

O caso mais traicoeiro e a porta do inventario: aqui ela se chama
`INVENTARIO_PORT` e no `.env` dele, `FRONTEND_PORT`.  Nomes diferentes, mesmo
valor — e se divergirem o Keycloak recusa o `redirect_uri` com um "Invalid
parameter" que nao explica nada.

Uso:
    python scripts/sync_host_ip.py            # aplica
    python scripts/sync_host_ip.py --check    # so verifica, nao escreve
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent
PROJETOS = INFRA.parent

INVENTARIO = PROJETOS / "Gerenciamento_de_inventario"
RECEITA = PROJETOS / "Gerencimento_de_receita"
DESPESA = PROJETOS / "Sistema_Despesa"
CONTROLE = PROJETOS / "Controle_Despesa"


@dataclass(frozen=True)
class Copia:
    """Um valor do infra/.env que precisa existir em outro .env."""

    destino: Path
    origem: str          # nome da variavel no infra/.env
    nome_destino: str    # nome dela no arquivo de destino
    porque: str


# A porta do Keycloak nao vem do infra/.env (e fixa em 8080 no compose dele),
# mas a receita precisa dela para montar o issuer.
CONSTANTES = {"KEYCLOAK_PORT": "8080"}

COPIAS = [
    # --- HOST_IP: todo mundo precisa ---------------------------------------
    Copia(INVENTARIO / ".env", "HOST_IP", "HOST_IP", "issuer do realm"),
    Copia(RECEITA / ".env", "HOST_IP", "HOST_IP", "issuer do realm"),
    Copia(DESPESA / ".env", "HOST_IP", "HOST_IP", "issuer do realm"),
    Copia(CONTROLE / ".env", "HOST_IP", "HOST_IP", "issuer do realm"),

    # --- Conta mestra: os tres precisam reconhecer o MESMO email ------------
    # E o unico endereco que vira admin dos tres sistemas. Se um dos .env
    # divergir, a conta seria admin em dois lugares e usuario comum no terceiro
    # — exatamente a confusao que ela existe para evitar.
    Copia(INVENTARIO / ".env", "ADMIN_MESTRE_EMAIL", "ADMIN_MESTRE_EMAIL",
          "conta que administra os tres sistemas"),
    Copia(RECEITA / ".env", "ADMIN_MESTRE_EMAIL", "ADMIN_MESTRE_EMAIL",
          "conta que administra os tres sistemas"),
    Copia(DESPESA / ".env", "ADMIN_MESTRE_EMAIL", "ADMIN_MESTRE_EMAIL",
          "conta que administra os tres sistemas"),
    Copia(CONTROLE / ".env", "ADMIN_MESTRE_EMAIL", "ADMIN_MESTRE_EMAIL",
          "conta que administra os tres sistemas"),

    # --- Client secrets: cada app tem o seu ---------------------------------
    Copia(INVENTARIO / ".env", "INVENTARIO_CLIENT_SECRET",
          "INVENTARIO_CLIENT_SECRET", "segredo do client inventario-web"),
    Copia(RECEITA / ".env", "RECEITA_CLIENT_SECRET",
          "OIDC_CLIENT_SECRET", "segredo do client receita-web"),
    Copia(DESPESA / ".env", "DESPESA_CLIENT_SECRET",
          "DESPESA_CLIENT_SECRET", "segredo do client despesa-web"),
    Copia(CONTROLE / ".env", "CONTROLE_DESPESA_CLIENT_SECRET",
          "CONTROLE_DESPESA_CLIENT_SECRET", "segredo do client controle-despesa-web"),

    # --- Portas: entram nos redirect URIs do realm --------------------------
    # NOMES DIFERENTES para o mesmo valor. Se divergirem, o Keycloak recusa o
    # redirect_uri e o login falha com "Invalid parameter".
    Copia(INVENTARIO / ".env", "INVENTARIO_PORT", "FRONTEND_PORT",
          "porta publicada do inventario (= INVENTARIO_PORT no realm)"),
    Copia(RECEITA / ".env", "RECEITA_PORT", "RECEITA_PORT",
          "porta publicada da receita"),
    Copia(RECEITA / ".env", "PORTAL_PORT", "PORTAL_PORT",
          "para onde mandar quem nao tem acesso"),
    # O inventario alcanca a API da receita por esta porta.
    Copia(INVENTARIO / ".env", "RECEITA_PORT", "RECEITA_PORT",
          "onde o sync busca os centros de custo"),

    # --- Portas para o seletor "Sistemas" dentro de cada app ----------------
    # Cada sistema oferece um atalho para o portal e para os outros; sem estas
    # portas os links apontariam para o lugar errado.
    Copia(INVENTARIO / ".env", "PORTAL_PORT", "PORTAL_PORT", "atalho para o portal"),
    Copia(INVENTARIO / ".env", "INVENTARIO_PORT", "INVENTARIO_PORT", "seletor de sistemas"),
    Copia(INVENTARIO / ".env", "DESPESA_PORT", "DESPESA_PORT", "seletor de sistemas"),
    Copia(DESPESA / ".env", "PORTAL_PORT", "PORTAL_PORT", "atalho para o portal"),
    Copia(DESPESA / ".env", "INVENTARIO_PORT", "INVENTARIO_PORT", "seletor de sistemas"),
    Copia(DESPESA / ".env", "RECEITA_PORT", "RECEITA_PORT", "seletor de sistemas"),
    Copia(DESPESA / ".env", "DESPESA_PORT", "DESPESA_PORT", "seletor de sistemas"),
    Copia(RECEITA / ".env", "INVENTARIO_PORT", "INVENTARIO_PORT", "seletor de sistemas"),
    Copia(RECEITA / ".env", "DESPESA_PORT", "DESPESA_PORT", "seletor de sistemas"),

    # --- Controle de Despesa (o quinto sistema) ----------------------------
    Copia(CONTROLE / ".env", "CONTROLE_DESPESA_PORT", "CONTROLE_DESPESA_PORT",
          "porta publicada (= CONTROLE_DESPESA_PORT no realm)"),
    Copia(CONTROLE / ".env", "PORTAL_PORT", "PORTAL_PORT", "atalho para o portal"),
    Copia(CONTROLE / ".env", "INVENTARIO_PORT", "INVENTARIO_PORT", "seletor de sistemas"),
    Copia(CONTROLE / ".env", "RECEITA_PORT", "RECEITA_PORT", "seletor de sistemas"),
    Copia(CONTROLE / ".env", "DESPESA_PORT", "DESPESA_PORT", "seletor de sistemas"),
    # Os outros quatro tambem precisam saber onde ele fica.
    Copia(INVENTARIO / ".env", "CONTROLE_DESPESA_PORT", "CONTROLE_DESPESA_PORT",
          "seletor de sistemas"),
    Copia(RECEITA / ".env", "CONTROLE_DESPESA_PORT", "CONTROLE_DESPESA_PORT",
          "seletor de sistemas"),
    Copia(DESPESA / ".env", "CONTROLE_DESPESA_PORT", "CONTROLE_DESPESA_PORT",
          "seletor de sistemas"),
]

# O token da API de sync nasce no .env da receita (ela e a dona) e o inventario
# precisa do mesmo valor. Nao passa pelo infra/.env.
TOKEN_SYNC = Copia(
    INVENTARIO / ".env", "SYNC_API_TOKEN", "RECEITA_API_TOKEN",
    "token da API de sincronizacao (nasce no .env da receita)"
)


def ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip()
    return valores


def escrever(destino: Path, nome: str, valor: str, apenas_checar: bool) -> str:
    """Grava (ou confere) `nome=valor` em `destino`."""
    if not destino.exists():
        return "AUSENTE (copie o .env.example do projeto primeiro)"

    texto = destino.read_text(encoding="utf-8")
    padrao = re.compile(rf"^{re.escape(nome)}\s*=.*$", re.MULTILINE)
    nova = f"{nome}={valor}"

    achado = padrao.search(texto)
    if achado:
        if achado.group(0).strip() == nova:
            return "ja em dia"
        acao = f"atualizado ({achado.group(0).strip()[:40]} -> {nova[:40]})"
        novo_texto = padrao.sub(nova, texto)
    else:
        acao = f"acrescentado ({nova[:50]})"
        novo_texto = texto.rstrip("\n") + "\n" + nova + "\n"

    if apenas_checar:
        return "DIVERGENTE: " + acao
    destino.write_text(novo_texto, encoding="utf-8")
    return acao


def ips_locais() -> set[str]:
    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        return set(addrs)
    except OSError:
        return set()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="so verifica, nao escreve")
    args = p.parse_args()

    infra_env = ler_env(INFRA / ".env")
    if not infra_env:
        sys.exit(
            f"ERRO: {INFRA / '.env'} nao existe ou esta vazio.\n"
            "  Copie o .env.example e preencha antes de rodar."
        )

    faltando = [
        c.origem for c in COPIAS if not infra_env.get(c.origem)
    ]
    if faltando:
        sys.exit(
            "ERRO: faltam valores no infra/.env: "
            + ", ".join(sorted(set(faltando)))
        )

    host_ip = infra_env["HOST_IP"]
    print(f"HOST_IP = {host_ip}   (fonte: infra/.env)\n")

    divergiu = False
    por_destino: dict[Path, list[str]] = {}

    for copia in COPIAS:
        resultado = escrever(
            copia.destino, copia.nome_destino, infra_env[copia.origem], args.check
        )
        if resultado.startswith(("DIVERGENTE", "AUSENTE")):
            divergiu = True
        por_destino.setdefault(copia.destino, []).append(
            f"    {copia.nome_destino:<26} {resultado}"
        )

    # Constantes que nao vem do infra/.env
    for nome, valor in CONSTANTES.items():
        resultado = escrever(RECEITA / ".env", nome, valor, args.check)
        if resultado.startswith(("DIVERGENTE", "AUSENTE")):
            divergiu = True
        por_destino.setdefault(RECEITA / ".env", []).append(
            f"    {nome:<26} {resultado}"
        )

    # Token da API de sync: a fonte e o .env da receita, nao o do infra.
    receita_env = ler_env(RECEITA / ".env")
    token = receita_env.get(TOKEN_SYNC.origem)
    if token:
        resultado = escrever(
            TOKEN_SYNC.destino, TOKEN_SYNC.nome_destino, token, args.check
        )
        if resultado.startswith(("DIVERGENTE", "AUSENTE")):
            divergiu = True
        por_destino.setdefault(TOKEN_SYNC.destino, []).append(
            f"    {TOKEN_SYNC.nome_destino:<26} {resultado}"
        )
    else:
        print(
            "AVISO: SYNC_API_TOKEN nao esta no .env da receita — o sync de\n"
            "  centros de custo nao vai autenticar. Gere com: openssl rand -hex 32\n"
        )

    for destino, linhas in por_destino.items():
        print(f"  {destino.parent.name}/.env")
        for linha in linhas:
            print(linha)
        print()

    # Avisa, nao corrige: autodetectar erra com VPN, Wi-Fi e Ethernet
    # simultaneos, e o valor detectado ainda teria que chegar ao Keycloak.
    locais = ips_locais()
    if locais and host_ip not in locais:
        print(
            f"AVISO: o HOST_IP ({host_ip}) nao esta entre os IPs desta maquina "
            f"({', '.join(sorted(locais))}).\n"
            "  Normal se os containers rodam em outro servidor. Se deveriam rodar\n"
            "  aqui, confira a reserva de DHCP antes de subir o Keycloak — o IP\n"
            "  entra no issuer do realm."
        )

    if args.check and divergiu:
        print("\n--check: ha divergencia. Rode sem --check para aplicar.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
