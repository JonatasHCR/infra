"""Confere, rota a rota, se há dependência de autenticação nos backends FastAPI.

Feito com AST, e não com regex: a guarda costuma chegar por um alias
(`T_UserContext = Annotated[UserContext, Depends(...)]`), e procurar pelo nome
da função de autenticação na linha do decorador não encontra nada.

    python scripts/rotas_sem_guarda.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJETOS = Path(__file__).resolve().parent.parent.parent

BACKENDS = {
    "radar": PROJETOS / "Sistema_Despesa" / "backend",
    "inventário": PROJETOS / "Gerenciamento_de_inventario" / "backend",
}

# Nomes de dependência que representam "quem é o usuário desta requisição".
AUTENTICACAO = (
    "get_current_user",
    "get_current_admin",
    "get_user_context",
    "current_user",
    "verificar_token",
)

METODOS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Rotas que existem justamente para quem ainda não entrou.
PUBLICAS = ("/health", "/docs", "/openapi", "/login", "/callback", "/token")


def eh_dependencia_de_auth(no: ast.AST) -> bool:
    """O nó menciona alguma função de autenticação?"""
    for filho in ast.walk(no):
        if isinstance(filho, ast.Name) and filho.id in AUTENTICACAO:
            return True
        if isinstance(filho, ast.Attribute) and filho.attr in AUTENTICACAO:
            return True
    return False


def aliases_de_auth(arvore: ast.Module) -> set[str]:
    """`T_UserContext = Annotated[UserContext, Depends(get_user_context)]`."""
    achados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and len(no.targets) == 1:
            alvo = no.targets[0]
            if isinstance(alvo, ast.Name) and eh_dependencia_de_auth(no.value):
                achados.add(alvo.id)
    return achados


def nome_do_tipo(anotacao: ast.AST | None) -> str:
    if anotacao is None:
        return ""
    if isinstance(anotacao, ast.Name):
        return anotacao.id
    if isinstance(anotacao, ast.Attribute):
        return anotacao.attr
    if isinstance(anotacao, ast.Subscript):
        return nome_do_tipo(anotacao.value)
    return ""


def rotas_do_arquivo(caminho: Path):
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return

    aliases = aliases_de_auth(arvore)

    # Router criado com dependência global protege tudo que pendura nele.
    router_protegido = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Call):
            chamada = no.value
            nome = getattr(chamada.func, "id", "") or getattr(chamada.func, "attr", "")
            if nome != "APIRouter":
                continue
            for palavra in chamada.keywords:
                if palavra.arg == "dependencies" and eh_dependencia_de_auth(palavra.value):
                    if isinstance(no.targets[0], ast.Name):
                        router_protegido.add(no.targets[0].id)

    for no in ast.walk(arvore):
        if not isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorador in no.decorator_list:
            if not isinstance(decorador, ast.Call):
                continue
            func = decorador.func
            if not isinstance(func, ast.Attribute) or func.attr not in METODOS:
                continue

            router = getattr(func.value, "id", "")
            caminho_rota = ""
            if decorador.args and isinstance(decorador.args[0], ast.Constant):
                caminho_rota = str(decorador.args[0].value)

            protegida = router in router_protegido
            if not protegida:
                protegida = any(eh_dependencia_de_auth(d) for d in no.decorator_list)
            if not protegida:
                for argumento in list(no.args.args) + list(no.args.kwonlyargs):
                    if nome_do_tipo(argumento.annotation) in aliases:
                        protegida = True
                        break
                    if argumento.annotation is not None and eh_dependencia_de_auth(
                        argumento.annotation
                    ):
                        protegida = True
                        break
            if not protegida and no.args.defaults:
                protegida = any(eh_dependencia_de_auth(d) for d in no.args.defaults)

            publica = any(p in caminho_rota.lower() for p in PUBLICAS)
            yield no.lineno, f"{func.attr.upper()} {caminho_rota or '/'}", protegida, publica

    # O radar registra por chamada, e nao por decorador:
    #   self.router.get("/x")(self._handler)
    # A guarda esta na assinatura de _handler.
    metodos = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            metodos[no.name] = no

    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Call):
            continue
        interna = no.func
        if not isinstance(interna.func, ast.Attribute) or interna.func.attr not in METODOS:
            continue

        caminho_rota = ""
        if interna.args and isinstance(interna.args[0], ast.Constant):
            caminho_rota = str(interna.args[0].value)

        alvo = no.args[0] if no.args else None
        nome_handler = ""
        if isinstance(alvo, ast.Attribute):
            nome_handler = alvo.attr
        elif isinstance(alvo, ast.Name):
            nome_handler = alvo.id

        handler = metodos.get(nome_handler)
        protegida = False
        if handler is not None:
            protegida = any(eh_dependencia_de_auth(d) for d in handler.args.defaults)
            if not protegida:
                for argumento in list(handler.args.args) + list(handler.args.kwonlyargs):
                    if argumento.annotation is not None and eh_dependencia_de_auth(
                        argumento.annotation
                    ):
                        protegida = True
                        break

        publica = any(p in caminho_rota.lower() for p in PUBLICAS)
        yield no.lineno, f"{interna.func.attr.upper()} {caminho_rota or '/'}", protegida, publica


def main() -> int:
    problemas = []

    for nome, raiz in BACKENDS.items():
        if not raiz.exists():
            print(f"{nome}: pasta não encontrada")
            continue

        total = protegidas = publicas = 0
        abertas = []

        for caminho in raiz.rglob("*.py"):
            texto = str(caminho).replace("\\", "/")
            if any(i in texto for i in (".venv", "site-packages", "__pycache__", "/tests/")):
                continue
            for linha, rota, protegida, publica in rotas_do_arquivo(caminho):
                total += 1
                if protegida:
                    protegidas += 1
                elif publica:
                    publicas += 1
                else:
                    relativo = str(caminho.relative_to(raiz)).replace("\\", "/")
                    abertas.append(f"{relativo}:{linha}  {rota}")

        print(f"\n{nome}: {total} rotas")
        print(f"   {protegidas} com dependência de autenticação")
        print(f"   {publicas} públicas por desenho (health, docs, login)")
        if abertas:
            print(f"   {len(abertas)} SEM guarda:")
            for aberta in abertas:
                print(f"      {aberta}")
            problemas.extend(abertas)
        else:
            print("   nenhuma rota desprotegida")

    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
