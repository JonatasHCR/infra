"""Cliente minimo da Admin API do Keycloak, compartilhado pelos scripts.

Usa so a biblioteca padrao: os scripts do infra rodam no Python do host, que nao
tem dependencia instalada.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REALM = "ufc"


def ler_env(caminho: Path | None = None) -> dict:
    valores = {}
    arquivo = caminho or (RAIZ / ".env")
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


class Keycloak:
    def __init__(self, base: str, usuario: str, senha: str):
        self.base = base.rstrip("/")
        self.acesso = self._token(usuario, senha)

    def _token(self, usuario: str, senha: str) -> str:
        dados = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": usuario,
                "password": senha,
            }
        ).encode()
        url = f"{self.base}/realms/master/protocol/openid-connect/token"
        with urllib.request.urlopen(urllib.request.Request(url, data=dados), timeout=20) as r:
            return json.load(r)["access_token"]

    def _pedir(self, metodo: str, caminho: str, corpo=None):
        url = f"{self.base}/admin/realms/{REALM}{caminho}"
        dados = json.dumps(corpo).encode() if corpo is not None else None
        cabecalhos = {"Authorization": f"Bearer {self.acesso}"}
        if dados:
            cabecalhos["Content-Type"] = "application/json"
        pedido = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            bruto = resposta.read()
            return json.loads(bruto) if bruto else None

    def get(self, caminho: str):
        return self._pedir("GET", caminho)

    def post(self, caminho: str, corpo):
        return self._pedir("POST", caminho, corpo)

    def put(self, caminho: str, corpo):
        return self._pedir("PUT", caminho, corpo)

    # --- conveniencias -----------------------------------------------------

    def clients(self) -> dict:
        return {c["clientId"]: c for c in self.get("/clients")}

    def grupos_com_filhos(self) -> dict:
        """path -> id, incluindo subgrupos.

        O /groups do Keycloak 26 nao devolve os filhos aninhados; e preciso
        pedir /children de cada um.
        """
        achados = {}

        def descer(lista):
            for grupo in lista:
                achados[grupo["path"]] = grupo["id"]
                descer(self.get(f"/groups/{grupo['id']}/children"))

        descer(self.get("/groups"))
        return achados

    def membros(self, identificador: str) -> list:
        return self.get(f"/groups/{identificador}/members")


def realm_versionado() -> dict:
    return json.loads((RAIZ / "keycloak" / "realm-ufc.json").read_text(encoding="utf-8"))


def renderizar(valor, env: dict):
    """Troca os ${VAR} do JSON pelos valores do .env, como o render-realm.sh."""
    if isinstance(valor, str):
        for chave, substituto in env.items():
            valor = valor.replace("${" + chave + "}", substituto)
        return valor
    if isinstance(valor, list):
        return [renderizar(item, env) for item in valor]
    if isinstance(valor, dict):
        return {chave: renderizar(item, env) for chave, item in valor.items()}
    return valor
