import 'server-only'

import { clientId, clientSecret, endpoints, issuer } from '@/lib/oidc'

/**
 * Cliente da Admin API do Keycloak — só para a tela de administração de acessos.
 *
 * Autentica por **client credentials**: o `portal-web` tem um service account
 * com as quatro permissões mínimas (`view-users`, `query-users`, `query-groups`,
 * `manage-users`). Não usa a senha de ninguém, e não tem `realm-admin` — não dá
 * para criar client, mexer no realm ou apagar nada além de usuário.
 *
 * `server-only` no topo: um import acidental disto num Client Component viraria
 * erro de build, e não um secret vazando no bundle.
 */

/**
 * Funcao, e nao constante de modulo: `issuer()` estoura se HOST_IP nao existir,
 * e no `next build` ele nao existe. Um const aqui derrubaria a build inteira
 * com um erro que nao menciona nem HOST_IP nem este arquivo.
 */
function baseAdmin(): string {
  return `${issuer().replace(/\/realms\/[^/]+$/, '')}/admin/realms/ufc`
}

export const GRUPO_ADMIN = '/admins'

export interface PessoaDoRealm {
  id: string
  email: string
  nome: string
  habilitado: boolean
  grupos: string[]
  /** true enquanto ainda não definiu a senha (importada ou recém-convidada). */
  aguardandoSenha: boolean
}

// O token do service account dura ~1 min. Guardamos em memória com margem, para
// não pedir um token novo a cada linha da tela.
let cache: { token: string; expiraEm: number } | null = null

async function token(): Promise<string> {
  const agora = Date.now()
  if (cache && cache.expiraEm > agora + 5_000) return cache.token

  const resp = await fetch(endpoints.token(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: clientId(),
      client_secret: clientSecret(),
    }),
    cache: 'no-store',
  })

  if (!resp.ok) {
    throw new Error(
      `Keycloak recusou o service account (${resp.status}). ` +
        'Confira se o portal-web tem serviceAccountsEnabled e os papéis de ' +
        'realm-management no realm.',
    )
  }

  const dados = await resp.json()
  cache = {
    token: dados.access_token,
    expiraEm: agora + dados.expires_in * 1000,
  }
  return cache.token
}

async function admin<T>(
  caminho: string,
  init: RequestInit = {},
): Promise<T | null> {
  const resp = await fetch(`${baseAdmin()}${caminho}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${await token()}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
    cache: 'no-store',
  })

  if (!resp.ok) {
    throw new Error(`Admin API ${init.method ?? 'GET'} ${caminho}: ${resp.status} ${await resp.text()}`)
  }

  const texto = await resp.text()
  return texto ? (JSON.parse(texto) as T) : null
}

/** Mapa {caminho: id} dos grupos, descendo nos subgrupos. */
export async function grupos(): Promise<Record<string, string>> {
  const mapa: Record<string, string> = {}

  async function descer(g: { id: string; path: string; subGroups?: unknown[]; subGroupCount?: number }) {
    mapa[g.path] = g.id
    const filhos =
      g.subGroups && (g.subGroups as []).length > 0
        ? (g.subGroups as typeof g[])
        : g.subGroupCount
          ? ((await admin<typeof g[]>(`/groups/${g.id}/children`)) ?? [])
          : []
    for (const f of filhos) await descer(f)
  }

  for (const raiz of (await admin<Parameters<typeof descer>[0][]>('/groups')) ?? []) {
    await descer(raiz)
  }
  return mapa
}

export async function pessoas(busca?: string): Promise<PessoaDoRealm[]> {
  const params = new URLSearchParams({ max: '200' })
  if (busca) params.set('search', busca)

  const brutos =
    (await admin<
      {
        id: string
        email?: string
        username: string
        firstName?: string
        lastName?: string
        enabled: boolean
        requiredActions?: string[]
      }[]
    >(`/users?${params}`)) ?? []

  // A listagem não traz os grupos; é uma chamada por pessoa. Em paralelo, porque
  // serial numa lista de 200 seria lento demais para uma tela.
  return Promise.all(
    brutos.map(async (u) => {
      const dela =
        (await admin<{ path: string }[]>(`/users/${u.id}/groups`)) ?? []
      return {
        id: u.id,
        email: u.email ?? u.username,
        nome: [u.firstName, u.lastName].filter(Boolean).join(' ') || u.username,
        habilitado: u.enabled,
        grupos: dela.map((g) => g.path),
        aguardandoSenha: (u.requiredActions ?? []).includes('UPDATE_PASSWORD'),
      }
    }),
  )
}

export async function entrarNoGrupo(usuarioId: string, grupoId: string) {
  await admin(`/users/${usuarioId}/groups/${grupoId}`, { method: 'PUT' })
}

export async function sairDoGrupo(usuarioId: string, grupoId: string) {
  await admin(`/users/${usuarioId}/groups/${grupoId}`, { method: 'DELETE' })
}

/**
 * Cria a pessoa **sem credencial**, com UPDATE_PASSWORD obrigatório — a mesma
 * regra da importação inicial. Ela define a senha no primeiro acesso.
 */
export async function convidar(dados: {
  email: string
  nome: string
  grupos: string[]
}): Promise<void> {
  const partes = dados.nome.trim().split(/\s+/)
  const mapa = await grupos()

  await admin('/users', {
    method: 'POST',
    body: JSON.stringify({
      username: dados.email,
      email: dados.email,
      // firstName/lastName são obrigatórios no perfil padrão do Keycloak. Sem
      // eles a pessoa até é criada, mas o login falha com "Account is not fully
      // set up" — e a mensagem não diz o que está faltando.
      firstName: partes[0] ?? dados.email,
      lastName: partes.slice(1).join(' ') || '-',
      enabled: true,
      emailVerified: true,
      requiredActions: ['UPDATE_PASSWORD'],
    }),
  })

  const criada = (await admin<{ id: string }[]>(
    `/users?${new URLSearchParams({ email: dados.email, exact: 'true' })}`,
  )) ?? []
  if (!criada[0]) throw new Error('Criei a pessoa mas não consegui reler o id.')

  for (const caminho of dados.grupos) {
    const id = mapa[caminho]
    if (id) await entrarNoGrupo(criada[0].id, id)
  }
}
