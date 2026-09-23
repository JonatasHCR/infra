#!/usr/bin/env python3
"""Reconstroi acentos perdidos ("Manuten??o" -> "Manutencao" com acento) nos bancos.

Um restore feito por pipe do PowerShell gravou "?" no lugar de cada letra
acentuada. O byte original se perdeu, entao cada palavra estragada e comparada
com um dicionario: palavras acentuadas que existem integras nos quatro bancos
mais a lista embutida abaixo. So troca quando ha um candidato claro; o resto
vai para o relatorio.

Uso:
    python scripts/corrigir_acentos.py                    # relatorio, nao grava
    python scripts/corrigir_acentos.py --aplicar          # grava (faz dump antes)
    python scripts/corrigir_acentos.py --sistema receita  # so um sistema
    python scripts/corrigir_acentos.py --prod             # usa docker-compose.prod.yml
    python scripts/corrigir_acentos.py --dicionario extra.txt
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent
PROJETOS = INFRA.parent


@dataclass(frozen=True)
class Fonte:
    rotulo: str
    diretorio: Path
    servico: str


FONTES = [
    Fonte("controle_despesa", PROJETOS / "Controle_Despesa", "db"),
    Fonte("radar", PROJETOS / "Sistema_Despesa", "db"),
    Fonte("inventario", PROJETOS / "Gerenciamento_de_inventario", "postgres"),
    Fonte("receita", PROJETOS / "Gerencimento_de_receita", "db"),
]

TABELAS_IGNORADAS = {"alembic_version", "schema_migrations", "ar_internal_metadata"}
COLUNA_SENSIVEL = re.compile(r"password|senha|token|digest|hash|secret|otp|encrypted", re.I)

ACENTUADAS = set("áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ")
PALAVRA = re.compile(r"(?:[^\W\d_]|\?)+")
CONSOANTES = set("bcdfghjklmnpqrstvwxyz")

PALAVRAS_COMUNS = """
não são então também já está estão até após através só só também você vocês
ação ações administração alimentação alteração análise aprovação área áreas
aquisição atenção atualização avaliação básico bancário cálculo câmara câmera
caminhão caminhões código comissão compensação competência composição comunicação
conclusão condição condições configuração construção consultoria contratação
contratações contribuição coordenação crédito créditos cessão decisão declaração
depósito descrição destinação diária diárias difusão direção distribuição
divisão documentação doação edificação educação elaboração elétrica elétrico
elétricos eletrônico eletrônicos emissão empréstimo energética engenharia
equipamento especificação estação estágio execução exercício expansão exposição
fabricação fatura físico física fiscalização formação função fundação
gestão gráfica gráfico gratificação hidráulica hidráulico histórico horário
iluminação implantação importação impressão indenização informação informações
infraestrutura inscrição inspeção instalação instalações instituição integração
intervenção inventário jurídico jurídica laboratório legislação licitação
licença licenças lógica locação logística manutenção máquina máquinas matéria
materiais médio médico médica medição medições mês meses métrico migração
ministério módulo monitoração movimentação município municipal navegação
negociação nível notificação número números obrigação observação observações
ocupação operação operações orçamento orçamentos órgão órgãos padrão padrões
página páginas parâmetro participação passagem patrimônio pavimentação
período períodos pesquisa pintura plástico polícia população posição prédio
prédios preço preços prestação previdência prêmio produção programação
promoção proporção prorrogação próprio própria proteção provisão público
pública públicos públicas publicação química químico razão realização
recepção recuperação redução reforma região relatório relatórios remoção
remuneração reparação reposição representação requisição rescisão reserva
residência resolução responsável restauração retenção reunião revisão
saída salário salários saúde seção segurança seleção serviço serviços
situação solicitação solução substituição sustentação técnica técnico
técnicos técnicas telefônica telefônico término título transferência
transição transmissão transporte tributação unidade único única usuário
usuários utilização válido válida variação veículo veículos vigência
visitação vistoria água águas elétrico ênfase época índice índices início
ícone óleo ônibus útil úteis agência agências ambiência audiência ciência
conferência consequência dependência diligência emergência experiência
frequência gerência influência licença potência presidência providência
referência sequência tendência ausência assistência convivência distância
importância instância substância tolerância circunstância abundância
estância relevância ânimo acadêmico acadêmica econômico econômica
administrativo coleção comercialização cópia cópias crachá fábrica
faculdade lâmpada lâmpadas mecânica mecânico mínimo máximo média médias
memória ótimo portaria série séries ata cotação cotações
pagável aplicável disponível possível responsáveis sustentável variável
estável imóvel imóveis móvel móveis automóvel papéis anéis hotéis
são joão josé maria antônio antônia conceição fortaleza ceará paraná
maranhão pará piauí amapá goiás espírito brasília são paulo belém
cícero jônatas márcio lúcia luís cláudio cláudia sérgio fábio flávio
vitória glória mônica patrícia letícia júlia júlio rogério otávio
"""


def construir_argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--aplicar", action="store_true", help="grava as correcoes no banco")
    p.add_argument("--sistema", choices=[f.rotulo for f in FONTES], action="append",
                   help="sistema a corrigir (pode repetir); padrao: todos")
    p.add_argument("--prod", action="store_true", help="usa docker-compose.prod.yml")
    p.add_argument("--dicionario", type=Path, help="arquivo com palavras acentuadas extras")
    p.add_argument("--saida", type=Path, default=INFRA / "relatorios_acentos",
                   help="pasta dos relatorios CSV")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Acesso ao banco
# ---------------------------------------------------------------------------

def compose(fonte: Fonte, prod: bool) -> list[str]:
    cmd = ["docker", "compose"]
    if prod:
        cmd += ["-f", str(fonte.diretorio / "docker-compose.prod.yml")]
    return cmd


def rodar(fonte: Fonte, prod: bool, args: list[str], entrada: bytes | None = None) -> str:
    if not fonte.diretorio.is_dir():
        raise RuntimeError(f"[{fonte.rotulo}] pasta nao encontrada: {fonte.diretorio}")
    try:
        r = subprocess.run(compose(fonte, prod) + args, cwd=fonte.diretorio,
                           input=entrada, capture_output=True)
    except OSError as e:
        raise RuntimeError(f"[{fonte.rotulo}] nao consegui rodar o docker: {e}") from e
    if r.returncode != 0:
        erro = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"[{fonte.rotulo}] {erro}")
    return r.stdout.decode("utf-8")


def sql(fonte: Fonte, prod: bool, comando: str, transacao: bool = False) -> list[list[str]]:
    psql = 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --csv -t'
    if transacao:
        psql += " --single-transaction"
    corpo = "SET client_encoding = 'UTF8';\n" + comando
    saida = rodar(fonte, prod, ["exec", "-T", fonte.servico, "sh", "-c", psql],
                  corpo.encode("utf-8"))
    return [linha for linha in csv.reader(io.StringIO(saida)) if linha]


def ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def literal(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


@dataclass(frozen=True)
class Coluna:
    tabela: str
    coluna: str
    pk: str


def colunas_texto(fonte: Fonte, prod: bool) -> list[Coluna]:
    linhas = sql(fonte, prod, """
        SELECT c.relname, a.attname, pa.attname
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary AND i.indnkeyatts = 1
        JOIN pg_attribute pa ON pa.attrelid = c.oid AND pa.attnum = i.indkey[0]
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
          AND a.attnum > 0 AND NOT a.attisdropped
          AND a.atttypid IN ('text'::regtype, 'varchar'::regtype, 'bpchar'::regtype)
        ORDER BY 1, 2;
    """)
    return [Coluna(*l) for l in linhas
            if l[0] not in TABELAS_IGNORADAS and not COLUNA_SENSIVEL.search(l[1])]


def palavras_integras(fonte: Fonte, prod: bool, colunas: list[Coluna]) -> Counter:
    if not colunas:
        return Counter()
    partes = [
        f"SELECT regexp_split_to_table({ident(c.coluna)}, '[^[:alpha:]]+') AS w "
        f"FROM {ident(c.tabela)} WHERE {ident(c.coluna)} ~ '[^\\x01-\\x7e]' "
        f"AND position('?' IN {ident(c.coluna)}) = 0"
        for c in colunas
    ]
    consulta = ("SELECT lower(w), count(*) FROM (" + " UNION ALL ".join(partes)
                + ") s WHERE w ~ '[^\\x01-\\x7e]' GROUP BY 1;")
    return Counter({w: int(n) for w, n in sql(fonte, prod, consulta)})


def valores_estragados(fonte: Fonte, prod: bool, colunas: list[Coluna]) -> list[tuple[Coluna, str, str]]:
    if not colunas:
        return []
    partes = [
        f"SELECT {i}, {ident(c.pk)}::text, {ident(c.coluna)} FROM {ident(c.tabela)} "
        f"WHERE {ident(c.coluna)} ~ '[[:alpha:]]\\?|\\?[[:alpha:]]'"
        for i, c in enumerate(colunas)
    ]
    linhas = sql(fonte, prod, " UNION ALL ".join(partes) + ";")
    return [(colunas[int(i)], pk, valor) for i, pk, valor in linhas]


# ---------------------------------------------------------------------------
# Reconstrucao
# ---------------------------------------------------------------------------

@dataclass
class Dicionario:
    # esqueleto ("manuten??o") -> contagem de cada forma acentuada
    simples: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    # mesmo, com dois "?" por letra (texto UTF-8 lido como ANSI antes de virar ASCII)
    duplo: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    def adicionar(self, palavra: str, peso: int = 1) -> None:
        palavra = palavra.lower()
        if not any(ch in ACENTUADAS for ch in palavra):
            return
        self.simples["".join("?" if ch in ACENTUADAS else ch for ch in palavra)][palavra] += peso
        self.duplo["".join("??" if ch in ACENTUADAS else ch for ch in palavra)][palavra] += peso

    def buscar(self, esqueleto: str) -> str | None:
        for tabela in (self.simples, self.duplo):
            candidatos = tabela.get(esqueleto)
            if not candidatos:
                continue
            (primeiro, n1), *resto = candidatos.most_common(2)
            if not resto or n1 >= 3 * resto[0][1]:
                return primeiro
            return None  # ambiguo
        return None


def por_sufixo(esqueleto: str) -> str | None:
    """Regras seguras para quando a palavra nao esta no dicionario."""
    if esqueleto.count("?") == 2 and esqueleto.endswith("??o") and len(esqueleto) > 4:
        return esqueleto[:-3] + "ção"
    if esqueleto.count("?") == 2 and esqueleto.endswith("??es") and len(esqueleto) > 5:
        return esqueleto[:-4] + "ções"
    if (esqueleto.count("?") == 1 and esqueleto.endswith("?o") and len(esqueleto) > 2
            and esqueleto[-3] in CONSOANTES):
        return esqueleto[:-2] + "ão"
    return None


def aplicar_caixa(original: str, nova: str, inicio_frase: bool) -> str:
    letras = [ch for ch in original if ch.isalpha()]
    if len(letras) > 1 and all(ch.isupper() for ch in letras):
        return nova.upper()
    if original[0].isupper() or (original[0] == "?" and inicio_frase):
        return nova[0].upper() + nova[1:]
    return nova


def corrigir_texto(texto: str, dic: Dicionario) -> tuple[str, list[str]]:
    pendentes: list[str] = []

    def troca(m: re.Match) -> str:
        token = m.group(0)
        if "?" not in token or not any(ch.isalpha() for ch in token):
            return token
        # "Pago?" / "Pago??": interrogacao de verdade no fim da palavra
        miolo = token.rstrip("?")
        so_no_fim = "?" not in miolo
        esqueleto = token.lower()
        nova = dic.buscar(esqueleto)
        if nova is None and not so_no_fim:
            nova = por_sufixo(esqueleto)
        if nova is None:
            if not so_no_fim:
                pendentes.append(token)
            return token
        antes = texto[:m.start()].rstrip()
        inicio_frase = not antes or antes[-1] in ".!?:\n"
        return aplicar_caixa(token, nova, inicio_frase)

    return PALAVRA.sub(troca, texto), pendentes


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------

def backup(fonte: Fonte, prod: bool) -> Path:
    destino_dir = INFRA / "backups"
    destino_dir.mkdir(exist_ok=True)
    nome = f"{fonte.rotulo}_antes_acentos_{datetime.now():%Y%m%d_%H%M%S}.dump"
    rodar(fonte, prod, ["exec", "-T", fonte.servico, "sh", "-c",
                        'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/antes_acentos.dump'])
    destino = destino_dir / nome
    rodar(fonte, prod, ["cp", f"{fonte.servico}:/tmp/antes_acentos.dump", str(destino)])
    rodar(fonte, prod, ["exec", "-T", fonte.servico, "rm", "-f", "/tmp/antes_acentos.dump"])
    if not destino.exists() or destino.stat().st_size == 0:
        raise RuntimeError(f"[{fonte.rotulo}] backup vazio em {destino}")
    return destino


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = construir_argumentos()
    if args.sistema:
        alvos = [f for f in FONTES if f.rotulo in args.sistema]
    else:
        alvos = [f for f in FONTES if f.diretorio.is_dir()]
    for f in FONTES:
        if not f.diretorio.is_dir():
            print(f"aviso: {f.rotulo} ignorado, pasta nao encontrada: {f.diretorio}")

    dic = Dicionario()
    for palavra in PALAVRAS_COMUNS.split():
        dic.adicionar(palavra)
    if args.dicionario:
        for palavra in args.dicionario.read_text(encoding="utf-8").split():
            dic.adicionar(palavra, peso=10)

    # O dicionario usa os quatro bancos, mesmo quando so um sera corrigido.
    colunas: dict[str, list[Coluna]] = {}
    for fonte in FONTES:
        try:
            colunas[fonte.rotulo] = colunas_texto(fonte, args.prod)
            for palavra, n in palavras_integras(fonte, args.prod, colunas[fonte.rotulo]).items():
                dic.adicionar(palavra, n)
        except RuntimeError as e:
            if fonte in alvos:
                print(f"ERRO: {e}\n  Suba o banco: cd {fonte.diretorio.name} && docker compose up -d {fonte.servico}")
                return 1
            print(f"aviso: {e} — dicionario segue sem as palavras dele")

    args.saida.mkdir(exist_ok=True)
    for fonte in alvos:
        estragados = valores_estragados(fonte, args.prod, colunas[fonte.rotulo])
        relatorio = args.saida / f"{fonte.rotulo}.csv"
        updates: list[str] = []
        faltando: Counter = Counter()
        with relatorio.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["tabela", "coluna", "id", "antes", "depois", "status", "pendentes"])
            for col, pk, valor in estragados:
                novo, pendentes = corrigir_texto(valor, dic)
                faltando.update(pendentes)
                if novo == valor:
                    status = "nao_resolvido" if pendentes else "sem_mudanca"
                else:
                    status = "parcial" if pendentes else "corrigido"
                    updates.append(
                        f"UPDATE {ident(col.tabela)} SET {ident(col.coluna)} = {literal(novo)} "
                        f"WHERE {ident(col.pk)}::text = {literal(pk)} "
                        f"AND {ident(col.coluna)} = {literal(valor)};"
                    )
                w.writerow([col.tabela, col.coluna, pk, valor, novo, status, " ".join(pendentes)])

        print(f"\n== {fonte.rotulo}: {len(estragados)} valores com '?', "
              f"{len(updates)} corrigiveis -> {relatorio}")
        if faltando:
            print("   palavras sem correcao (adicione a forma certa num --dicionario):")
            for token, n in faltando.most_common(15):
                print(f"     {n:5}  {token}")

        if args.aplicar and updates:
            arquivo = backup(fonte, args.prod)
            print(f"   backup: {arquivo}")
            sql(fonte, args.prod, "\n".join(updates), transacao=True)
            print(f"   {len(updates)} valores gravados.")

    if not args.aplicar:
        print("\nNada foi gravado. Confira os CSV e rode de novo com --aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
