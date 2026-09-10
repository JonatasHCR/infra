/**
 * O catalogo. E a UNICA coisa que muda quando entra um quarto sistema.
 *
 * `process.env.HOST_IP` e lido em RUNTIME, e isso so funciona em codigo de
 * servidor. Num Client Component seria preciso o prefixo `NEXT_PUBLIC_`, que e
 * assado na imagem em tempo de build — e ai o IP voltaria a ficar preso dentro
 * de artefatos. Como o BFF mantem tudo no servidor, a variavel comum basta.
 */

export interface Sistema {
  /** Grupo do Keycloak que da acesso. Caminho completo — o mapper usa full.path. */
  grupo: string
  nome: string
  descricao: string
  url: string
}

export function sistemas(): Sistema[] {
  const host = `http://${process.env.HOST_IP}`
  // As portas vem do ambiente pelo mesmo motivo que o IP: elas tambem entram
  // nos redirect URIs do realm, e os dois lados precisam concordar. O
  // inventario nao usa 3000 — o .env dele ja vinha com 3030.
  return [
    {
      grupo: '/apps/inventario',
      nome: 'Inventario',
      descricao: 'Eletronicos, cessoes e solicitacoes por centro de custo.',
      url: `${host}:${process.env.INVENTARIO_PORT ?? '3030'}`,
    },
    {
      grupo: '/apps/receita',
      nome: 'Receita',
      descricao: 'Centros de custo, contratos, clientes e faturamento.',
      url: `${host}:${process.env.RECEITA_PORT ?? '3040'}`,
    },
    {
      grupo: '/apps/despesa',
      nome: 'Radar',
      descricao: 'Lancamento e acompanhamento de despesas.',
      url: `${host}:${process.env.DESPESA_PORT ?? '3010'}`,
    },
    {
      grupo: '/apps/controle-despesa',
      nome: 'Controle de Despesa',
      descricao: 'Despesas por centro de custo, com importacao de planilha e relatorios.',
      url: `${host}:${process.env.CONTROLE_DESPESA_PORT ?? '3050'}`,
    },
  ]
}

/**
 * Filtra pelo que o usuario pode ver. Roda no SERVIDOR: o navegador nem recebe
 * a lista do que nao pode acessar.
 *
 * Isto ESCONDE, nao protege. Quem souber a URL vai tentar entrar direto — quem
 * barra e a checagem de grupo no backend de cada sistema (Fases 2 a 4).
 */
export function sistemasDoUsuario(grupos: string[]): Sistema[] {
  return sistemas().filter((s) => grupos.includes(s.grupo))
}
