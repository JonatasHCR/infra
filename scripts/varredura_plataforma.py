"""Varredura estática dos quatro sistemas da plataforma.

Os stacks são diferentes — FastAPI, FastAPI, Rails e Next.js —, então em vez de
exercitar cada um no ar, isto procura os padrões que costumam abrir buraco:
rota sem guarda, SQL montado por concatenação, HTML marcado como seguro,
segredo no repositório e container rodando como root em produção.

    python scripts/varredura_plataforma.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJETOS = Path(__file__).resolve().parent.parent.parent

SISTEMAS = {
    "radar (Sistema_Despesa)": PROJETOS / "Sistema_Despesa",
    "inventário": PROJETOS / "Gerenciamento_de_inventario",
    "receita": PROJETOS / "Gerencimento_de_receita",
    "infra (portal)": PROJETOS / "infra",
}

IGNORAR = (
    "node_modules", ".git", "__pycache__", ".next", "vendor/bundle",
    "postgres_data", "backups", "dist", "coverage", ".pytest_cache",
    "tmp/", "log/", "public/assets", "builds/",
    # Dependencia de terceiro nao e codigo da casa; o ruido afogava o sinal.
    ".venv", "site-packages", "/venv/", ".tox", "migrations/versions",
)


@dataclass
class Achado:
    gravidade: str
    sistema: str
    titulo: str
    onde: list[str] = field(default_factory=list)
    nota: str = ""


achados: list[Achado] = []


def anotar(gravidade, sistema, titulo, onde=None, nota=""):
    achados.append(Achado(gravidade, sistema, titulo, onde or [], nota))


def arquivos(raiz: Path, *sufixos: str):
    proprio = Path(__file__).resolve()
    for caminho in raiz.rglob("*"):
        if caminho.resolve() == proprio:
            continue
        if not caminho.is_file() or caminho.suffix not in sufixos:
            continue
        texto = str(caminho).replace("\\", "/")
        if any(i in texto for i in IGNORAR):
            continue
        yield caminho


def linhas_com(caminho: Path, padrao: re.Pattern):
    try:
        conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for numero, linha in enumerate(conteudo.splitlines(), 1):
        if padrao.search(linha):
            yield numero, linha.strip()


def curto(caminho: Path, raiz: Path) -> str:
    return str(caminho.relative_to(raiz)).replace("\\", "/")


# --- 1. rotas sem guarda ----------------------------------------------------

ROTA_FASTAPI = re.compile(r"@\w*\.?(get|post|put|patch|delete)\s*\(")
GUARDA_FASTAPI = re.compile(r"Depends\s*\(\s*(get_current_user|get_current_admin|\w*current\w*)")


def rotas_fastapi(sistema: str, raiz: Path) -> None:
    """A cobertura de guarda mora em scripts/rotas_sem_guarda.py.

    Regex nao da conta: a guarda chega por alias
    (`T_UserContext = Annotated[..., Depends(...)]`) ou por registro em
    chamada (`self.router.get(...)(handler)`). Aquele script le a AST.
    """
    print(f"   {sistema}: guarda de rota — ver scripts/rotas_sem_guarda.py")


def rotas_rails(sistema: str, raiz: Path) -> None:
    controladores = list(arquivos(raiz / "app" / "controllers", ".rb"))
    sem_authorize = []
    for caminho in controladores:
        conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
        if "ApplicationController" in conteudo and "class ApplicationController" in conteudo:
            continue
        if "ActionController::API" in conteudo:
            continue  # API de servico, autenticada por token
        acoes = re.findall(r"^\s+def (index|show|new|create|edit|update|destroy)\b", conteudo, re.M)
        if not acoes:
            continue
        if "authorize" not in conteudo and "policy_scope" not in conteudo:
            sem_authorize.append(f"{curto(caminho, raiz)}  ({len(acoes)} ações)")

    if sem_authorize:
        anotar(
            "REVISAR", sistema, "Controlador sem authorize/policy_scope",
            sem_authorize[:10],
            "O Pundit pode estar aplicado por before_action no ApplicationController.",
        )
    else:
        print(f"   {sistema}: {len(controladores)} controladores, todos com Pundit aparente")


# --- 2. SQL montado por concatenação ---------------------------------------

SQL_PERIGOSO = [
    (re.compile(r"""(execute|text)\s*\(\s*f['"]"""), "f-string dentro de execute/text"),
    (re.compile(r"""(execute|text)\s*\(\s*['"].*?%s?['"]\s*%\s"""), "interpolação com %"),
    (re.compile(r"""(execute|text)\s*\([^)]*\+\s*\w"""), "concatenação com +"),
    (re.compile(r"""where\s*\(\s*["'][^"']*#\{"""), "interpolação Ruby em where"),
    (re.compile(r"""(find_by_sql|execute)\s*\(\s*["'][^"']*#\{"""), "interpolação Ruby em SQL"),
]


def sql_inseguro(sistema: str, raiz: Path) -> None:
    encontrados = []
    for caminho in arquivos(raiz, ".py", ".rb"):
        for padrao, rotulo in SQL_PERIGOSO:
            for numero, linha in linhas_com(caminho, padrao):
                encontrados.append(f"{curto(caminho, raiz)}:{numero}  [{rotulo}]  {linha[:64]}")

    if encontrados:
        anotar(
            "ALTA", sistema, "SQL montado por concatenação",
            encontrados[:10],
            "Valor vindo do usuário concatenado em SQL é injeção.",
        )
    else:
        print(f"   {sistema}: nenhum SQL concatenado")


# --- 3. HTML marcado como seguro -------------------------------------------

# Cada padrao vale so onde faz sentido: `rawExpenses` num TSX nao e o
# helper raw() do Rails, e `| safe` do Jinja nao existe em TypeScript.
XSS = [
    (re.compile(r"\.html_safe\b"), "html_safe (Rails)", (".rb", ".erb")),
    (re.compile(r"<%=\s*raw[\s(]"), "raw() em view (Rails)", (".erb",)),
    (re.compile(r"dangerouslySetInnerHTML"), "dangerouslySetInnerHTML", (".tsx", ".jsx")),
    (re.compile(r"""return\s+f['\"]<\w[^'\"]*(class=|</)"""), "HTML em f-string", (".py",)),
    (re.compile(r"\|\s*safe\b"), "| safe (Jinja)", (".html",)),
]

# String literal marcada como segura e o proprio codigo, nao dado do usuario.
LITERAL_SEGURO = re.compile(r"""['\"]<[^'\"]*['\"]\s*\.html_safe""")


def xss(sistema: str, raiz: Path) -> None:
    encontrados = []
    for caminho in arquivos(raiz, ".py", ".rb", ".erb", ".tsx", ".jsx", ".html"):
        for padrao, rotulo, sufixos in XSS:
            if caminho.suffix not in sufixos:
                continue
            for numero, linha in linhas_com(caminho, padrao):
                if LITERAL_SEGURO.search(linha):
                    continue
                encontrados.append(f"{curto(caminho, raiz)}:{numero}  [{rotulo}]  {linha[:64]}")

    if encontrados:
        anotar(
            "REVISAR", sistema, "HTML marcado como seguro",
            encontrados[:10],
            "Legitimo com conteudo proprio; injecao se o valor vier do usuario.",
        )
    else:
        print(f"   {sistema}: nenhum HTML marcado como seguro")


# --- 4. segredo no repositório ---------------------------------------------

SEGREDO = re.compile(
    r"""(senha|password|secret|token|api_key)\s*[:=]\s*['"][^'"{$\s]{8,}['"]""",
    re.I,
)


def segredos(sistema: str, raiz: Path) -> None:
    encontrados = []
    for caminho in arquivos(raiz, ".py", ".rb", ".ts", ".tsx", ".json", ".yml", ".yaml"):
        nome = curto(caminho, raiz)
        if "test" in nome.lower() or "spec" in nome.lower() or "exemplo" in nome or "example" in nome:
            continue
        for numero, linha in linhas_com(caminho, SEGREDO):
            if re.search(r"(ENV|os\.environ|process\.env|getenv|fetch\()", linha):
                continue
            encontrados.append(f"{nome}:{numero}  {linha[:72]}")

    if encontrados:
        anotar(
            "ALTA", sistema, "Credencial escrita no código",
            encontrados[:10],
            "Sai no git, no backup e em qualquer cópia do repositório.",
        )
    else:
        print(f"   {sistema}: nenhuma credencial no código")


# --- 5. container como root em produção ------------------------------------


def containers(sistema: str, raiz: Path) -> None:
    de_producao = []
    for caminho in raiz.rglob("Dockerfile*"):
        nome = caminho.name
        if any(i in str(caminho).replace("\\", "/") for i in IGNORAR):
            continue
        if nome.endswith((".dev", ".bootstrap")):
            continue  # dev roda como root de propósito, para hot reload
        conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"^USER\s+\S", conteudo, re.M):
            de_producao.append(curto(caminho, raiz))

    if de_producao:
        anotar(
            "MÉDIA", sistema, "Container de produção roda como root",
            de_producao,
            "Sem USER no Dockerfile: comprometer a aplicação dá root no container.",
        )
    else:
        print(f"   {sistema}: containers de produção com usuário sem privilégio")


# --- 6. CORS e documentação exposta ----------------------------------------


def fastapi_extras(sistema: str, raiz: Path) -> None:
    problemas = []
    for caminho in arquivos(raiz, ".py"):
        for numero, linha in linhas_com(caminho, re.compile(r'allow_origins\s*=\s*\[\s*["\']\*')):
            problemas.append(f"{curto(caminho, raiz)}:{numero}  CORS liberado para qualquer origem")
        for numero, linha in linhas_com(caminho, re.compile(r"FastAPI\s*\(")):
            trecho = caminho.read_text(encoding="utf-8", errors="ignore")
            if "docs_url" not in trecho:
                problemas.append(
                    f"{curto(caminho, raiz)}:{numero}  Swagger no ar sem condição de ambiente"
                )
            break

    if problemas:
        anotar("MÉDIA", sistema, "Exposição da API", problemas[:6])


def main() -> int:
    print("=" * 78)
    print("VARREDURA ESTÁTICA — plataforma UFC Engenharia")
    print("=" * 78)

    for nome, raiz in SISTEMAS.items():
        if not raiz.exists():
            print(f"\n{nome}: pasta não encontrada ({raiz})")
            continue
        print(f"\n{nome}")
        containers(nome, raiz)
        sql_inseguro(nome, raiz)
        xss(nome, raiz)
        segredos(nome, raiz)
        if (raiz / "backend").exists() or nome.startswith("radar"):
            rotas_fastapi(nome, raiz)
            fastapi_extras(nome, raiz)
        if (raiz / "app" / "controllers").exists():
            rotas_rails(nome, raiz)

    print("\n" + "=" * 78)
    if not achados:
        print("nenhum achado.")
        return 0

    ordem = {"ALTA": 0, "MÉDIA": 1, "REVISAR": 2}
    for achado in sorted(achados, key=lambda a: (ordem[a.gravidade], a.sistema)):
        print(f"\n[{achado.gravidade}] {achado.sistema} — {achado.titulo}")
        if achado.nota:
            print(f"    {achado.nota}")
        for onde in achado.onde:
            print(f"      {onde}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
