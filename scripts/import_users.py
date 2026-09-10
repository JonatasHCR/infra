#!/usr/bin/env python3
"""Importa os usuarios dos tres sistemas para o Keycloak.

Le os tres bancos, deduplica por email, cria cada pessoa no realm SEM CREDENCIAL
e com a acao obrigatoria UPDATE_PASSWORD (reset forcado — nenhum hash legado e
migrado), e associa cada uma aos grupos dos sistemas em que ja existia.  Essa
associacao e a migracao natural do acesso atual: quem usa dois sistemas hoje
entra nos dois grupos.

Os Postgres da despesa e da receita nao publicam porta no host, entao a leitura
e feita por `docker compose exec`, que nao exige mexer na rede dos composes nem
duplicar credenciais aqui.

Uso:
    python scripts/import_users.py              # relatorio, nao escreve nada
    python scripts/import_users.py --apply      # cria de fato no Keycloak
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent
PROJETOS = INFRA.parent
REALM = "ufc"


@dataclass(frozen=True)
class Fonte:
    """Um dos tres sistemas de origem."""

    rotulo: str
    diretorio: Path
    servico: str  # nome do servico postgres no compose daquele projeto
    consulta: str
    grupo: str
    usuario_padrao: str
    banco_padrao: str


FONTES = [
    Fonte(
        rotulo="inventario",
        diretorio=PROJETOS / "Gerenciamento_de_inventario",
        servico="postgres",
        consulta="SELECT email, nome FROM tb_users ORDER BY email",
        grupo="/apps/inventario",
        usuario_padrao="postgres",
        banco_padrao="postgres",
    ),
    Fonte(
        rotulo="receita",
        diretorio=PROJETOS / "Gerencimento_de_receita",
        servico="db",
        # a receita chama a coluna de nome de "name"
        consulta="SELECT email, name FROM users ORDER BY email",
        grupo="/apps/receita",
        usuario_padrao="receita",
        banco_padrao="receita_dev",
    ),
    Fonte(
        rotulo="despesa",
        diretorio=PROJETOS / "Sistema_Despesa",
        servico="db",
        consulta="SELECT email, nome FROM tb_users ORDER BY email",
        grupo="/apps/despesa",
        usuario_padrao="postgres",
        banco_padrao="postgres",
    ),
]


@dataclass
class Pessoa:
    email: str
    nomes: set[str] = field(default_factory=set)
    grupos: set[str] = field(default_factory=set)
    origens: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Leitura dos .env e dos bancos
# ---------------------------------------------------------------------------

def ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def coletar(fonte: Fonte) -> list[tuple[str, str]]:
    """Extrai (email, nome) de um sistema via `docker compose exec`."""
    env = ler_env(fonte.diretorio / ".env")
    usuario = env.get("POSTGRES_USER", fonte.usuario_padrao)
    banco = env.get("POSTGRES_DB", fonte.banco_padrao)

    comando = [
        "docker", "compose",
        "-f", str(fonte.diretorio / "docker-compose.yml"),
        "exec", "-T", fonte.servico,
        "psql", "-U", usuario, "-d", banco, "--csv", "-t", "-c", fonte.consulta,
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        erro = (resultado.stderr or resultado.stdout).strip()
        raise RuntimeError(
            f"falha lendo o banco do {fonte.rotulo}: {erro}\n"
            f"  O container precisa estar de pe: "
            f"cd {fonte.diretorio.name} && docker compose up -d {fonte.servico}"
        )

    linhas = []
    for campos in csv.reader(io.StringIO(resultado.stdout)):
        if len(campos) >= 2 and campos[0].strip():
            linhas.append((campos[0].strip(), campos[1].strip()))
    return linhas


# ---------------------------------------------------------------------------
# Consolidacao e relatorio de conflitos
# ---------------------------------------------------------------------------

EMAIL_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def consolidar(
    coletas: dict[str, list[tuple[str, str]]],
) -> tuple[dict[str, Pessoa], list[str]]:
    pessoas: dict[str, Pessoa] = {}
    avisos: list[str] = []
    grupo_de = {f.rotulo: f.grupo for f in FONTES}

    for rotulo, linhas in coletas.items():
        for email_bruto, nome in linhas:
            email = email_bruto.strip().lower()
            if not EMAIL_VALIDO.match(email):
                avisos.append(
                    f"  [{rotulo}] email invalido, IGNORADO: {email_bruto!r} (nome: {nome!r})"
                )
                continue
            pessoa = pessoas.setdefault(email, Pessoa(email=email))
            pessoa.nomes.add(nome)
            pessoa.grupos.add(grupo_de[rotulo])
            pessoa.origens.add(rotulo)

    # Mesma pessoa cadastrada com emails diferentes em sistemas diferentes: nao
    # da para resolver sozinho, so apontar.  Heuristica: nome identico
    # (normalizado) aparecendo sob mais de um email.
    por_nome: dict[str, set[str]] = defaultdict(set)
    for pessoa in pessoas.values():
        for nome in pessoa.nomes:
            chave = " ".join(nome.lower().split())
            if chave:
                por_nome[chave].add(pessoa.email)

    divergentes = [
        f"  {nome!r}: {', '.join(sorted(emails))}"
        for nome, emails in sorted(por_nome.items())
        if len(emails) > 1
    ]
    if divergentes:
        avisos += [
            "",
            "EMAILS DIVERGENTES (mesmo nome sob emails diferentes) — resolver a mao",
            "antes de importar, senao a pessoa vira duas contas no Keycloak:",
            *divergentes,
        ]

    return pessoas, avisos


# ---------------------------------------------------------------------------
# Keycloak Admin API
# ---------------------------------------------------------------------------

class Keycloak:
    def __init__(self, base: str, usuario: str, senha: str):
        self.base = base.rstrip("/")
        self._usuario = usuario
        self._senha = senha
        self.token = self._autenticar(usuario, senha)

    def _requisicao(self, metodo: str, caminho: str, corpo=None, _repetindo=False):
        dados = None
        cabecalhos = {"Authorization": f"Bearer {self.token}"}
        if corpo is not None:
            dados = json.dumps(corpo).encode()
            cabecalhos["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base}{caminho}", data=dados, headers=cabecalhos, method=metodo
        )
        try:
            with urllib.request.urlopen(req) as resp:
                texto = resp.read().decode()
        except urllib.error.HTTPError as e:
            # O token do admin-cli dura cerca de um minuto. Importar algumas
            # centenas de usuarios passa disso com folga, e sem isto o script
            # morreria no meio, com parte da importacao feita.
            if e.code == 401 and not _repetindo:
                self.token = self._autenticar(self._usuario, self._senha)
                return self._requisicao(metodo, caminho, corpo, _repetindo=True)
            raise
        return json.loads(texto) if texto.strip() else None

    def _autenticar(self, usuario: str, senha: str) -> str:
        dados = urllib.parse.urlencode({
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": usuario,
            "password": senha,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/realms/master/protocol/openid-connect/token",
            data=dados,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())["access_token"]

    def grupos(self) -> dict[str, str]:
        """Mapa {caminho: id}. Desce nos subgrupos — a partir do Keycloak 23 a
        listagem raiz nao os traz aninhados."""
        mapa: dict[str, str] = {}

        def descer(grupo: dict) -> None:
            mapa[grupo["path"]] = grupo["id"]
            filhos = grupo.get("subGroups")
            if not filhos and grupo.get("subGroupCount", 0):
                filhos = self._requisicao(
                    "GET", f"/admin/realms/{REALM}/groups/{grupo['id']}/children"
                ) or []
            for filho in filhos or []:
                descer(filho)

        for raiz in self._requisicao("GET", f"/admin/realms/{REALM}/groups") or []:
            descer(raiz)
        return mapa

    def buscar_usuario(self, email: str) -> str | None:
        consulta = urllib.parse.urlencode({"email": email, "exact": "true"})
        achados = self._requisicao("GET", f"/admin/realms/{REALM}/users?{consulta}") or []
        return achados[0]["id"] if achados else None

    def criar_usuario(self, pessoa: Pessoa) -> str:
        nome_completo = max(pessoa.nomes, key=len) if pessoa.nomes else ""
        partes = nome_completo.split()
        corpo = {
            "username": pessoa.email,
            "email": pessoa.email,
            "firstName": partes[0] if partes else "",
            "lastName": " ".join(partes[1:]) if len(partes) > 1 else "",
            "enabled": True,
            "emailVerified": True,
            # Sem "credentials": a conta nasce sem senha e a pessoa define a sua
            # no primeiro acesso.  Nenhum hash legado atravessa.
            "requiredActions": ["UPDATE_PASSWORD"],
        }
        self._requisicao("POST", f"/admin/realms/{REALM}/users", corpo)
        criado = self.buscar_usuario(pessoa.email)
        if not criado:
            raise RuntimeError(f"criei {pessoa.email} mas nao consegui reler o id")
        return criado

    def associar_grupo(self, usuario_id: str, grupo_id: str) -> None:
        self._requisicao(
            "PUT", f"/admin/realms/{REALM}/users/{usuario_id}/groups/{grupo_id}"
        )


# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--apply", action="store_true", help="cria de fato no Keycloak (sem isso, so relata)"
    )
    args = p.parse_args()

    env = ler_env(INFRA / ".env")
    host_ip = env.get("HOST_IP")
    if not host_ip:
        sys.exit("ERRO: HOST_IP nao definido em infra/.env.")

    print("Lendo os tres bancos...\n")
    coletas: dict[str, list[tuple[str, str]]] = {}
    for fonte in FONTES:
        try:
            coletas[fonte.rotulo] = coletar(fonte)
        except RuntimeError as e:
            sys.exit(f"ERRO: {e}")
        print(f"  {fonte.rotulo:<12} {len(coletas[fonte.rotulo]):>4} usuarios")

    pessoas, avisos = consolidar(coletas)
    total = sum(len(v) for v in coletas.values())
    print(f"\n  {total} cadastros -> {len(pessoas)} pessoas distintas (deduplicado por email)\n")

    por_qtd: dict[int, int] = defaultdict(int)
    for pessoa in pessoas.values():
        por_qtd[len(pessoa.grupos)] += 1
    for qtd in sorted(por_qtd):
        print(f"  {por_qtd[qtd]:>4} pessoas com acesso a {qtd} sistema(s)")

    if avisos:
        print("\n" + "\n".join(avisos))

    if not args.apply:
        print("\n--- relatorio apenas. Reveja os avisos e rode com --apply para importar. ---")
        return 0

    senha_admin = env.get("KC_ADMIN_PASSWORD")
    if not senha_admin:
        sys.exit("ERRO: KC_ADMIN_PASSWORD nao definido em infra/.env.")

    print(f"\nConectando ao Keycloak em http://{host_ip}:8080 ...")
    try:
        kc = Keycloak(f"http://{host_ip}:8080", env.get("KC_ADMIN", "admin"), senha_admin)
    except urllib.error.URLError as e:
        sys.exit(f"ERRO: nao consegui falar com o Keycloak: {e}")

    grupos = kc.grupos()
    faltando = {g for p in pessoas.values() for g in p.grupos} - grupos.keys()
    if faltando:
        sys.exit(f"ERRO: grupos ausentes no realm: {sorted(faltando)}. O realm foi importado?")

    criados = reaproveitados = 0
    for pessoa in sorted(pessoas.values(), key=lambda p: p.email):
        existente = kc.buscar_usuario(pessoa.email)
        if existente:
            usuario_id, marca = existente, "ja existia"
            reaproveitados += 1
        else:
            usuario_id, marca = kc.criar_usuario(pessoa), "criado"
            criados += 1
        for grupo in sorted(pessoa.grupos):
            kc.associar_grupo(usuario_id, grupos[grupo])
        print(f"  {pessoa.email:<40} {marca:<12} {', '.join(sorted(pessoa.origens))}")

    print(
        f"\n{criados} criados, {reaproveitados} ja existiam. "
        "Todos entram com UPDATE_PASSWORD — definem a senha no primeiro acesso."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
