import { cookies } from 'next/headers'

import { AlternadorDeTema } from '@/components/tema'
import { GRUPO_ADMIN } from '@/lib/admin'
import { baseUrl, clientId, endpoints } from '@/lib/oidc'
import { lerSessao } from '@/lib/session'
import { sistemasDoUsuario } from '@/lib/sistemas'

/**
 * Server Component: a filtragem acontece AQUI, no servidor. O navegador nem
 * recebe a lista dos sistemas a que a pessoa não tem acesso.
 *
 * O middleware já garantiu que existe sessão válida antes de chegar nesta
 * página; a leitura abaixo só a recupera.
 */

export const dynamic = 'force-dynamic'

// referrer/referrer_uri: sem eles o Account Console nao oferece volta. O
// referrer_uri precisa estar nos redirectUris do client, ou vem ignorado.
function urlDaConta(): string {
  const params = new URLSearchParams({
    referrer: clientId(),
    referrer_uri: `${baseUrl()}/`,
  })
  return `${endpoints.conta()}?${params}`
}

export default async function Pagina({
  searchParams,
}: {
  searchParams: Promise<{ erro?: string }>
}) {
  const sessao = await lerSessao(await cookies())
  const { erro } = await searchParams
  const disponiveis = sessao ? sistemasDoUsuario(sessao.groups) : []
  const primeiroNome = sessao?.name?.split(' ')[0] ?? ''
  // O link some para quem não é admin; quem for pela URL cai no redirect da
  // própria /admin, que revalida no servidor.
  const ehAdmin = sessao?.groups?.includes(GRUPO_ADMIN) ?? false

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-3xl flex-col px-6 py-14">
      <header className="mb-10 flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-display text-xl font-bold tracking-tight text-brand">
            UFC Engenharia
          </span>
          {primeiroNome && (
            <span className="text-sm text-muted">Olá, {primeiroNome}.</span>
          )}
        </div>

        <nav className="flex items-center gap-4 text-sm">
          {ehAdmin && <Elo href="/admin">Acessos</Elo>}
          <Elo href={urlDaConta()}>Minha conta</Elo>
          <Elo href="/api/auth/logout">Sair</Elo>
          <AlternadorDeTema />
        </nav>
      </header>

      {erro && (
        <p className="mb-6 rounded-md border border-hairline bg-aviso-soft px-4 py-3 text-sm text-aviso">
          {erro}
        </p>
      )}

      {disponiveis.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {disponiveis.map((sistema) => (
            <li key={sistema.grupo}>
              <a
                href={sistema.url}
                className="block h-full rounded border border-hairline border-l-[3px] border-l-brand bg-surface p-5 transition-colors hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
              >
                <h2 className="font-display text-base font-semibold text-ink">
                  {sistema.nome}
                </h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  {sistema.descricao}
                </p>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        // Uma tela vazia faria a pessoa achar que o sistema quebrou. Ela precisa
        // saber que o login deu certo e a quem pedir acesso.
        <div className="rounded border border-hairline bg-surface p-6">
          <h2 className="font-display font-semibold text-ink">
            Você entrou, mas ainda não tem acesso a nenhum sistema.
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Seu login funcionou — falta só a liberação. Peça a quem administra os
            acessos para incluir{' '}
            <strong className="text-ink">{sessao?.email}</strong> nos sistemas
            que você precisa usar.
          </p>
        </div>
      )}

      <footer className="mt-auto pt-12 text-xs text-faint">
        Uma senha só para os três sistemas. Troque a sua em &quot;Minha conta&quot;.
      </footer>
    </main>
  )
}

function Elo({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="text-muted underline-offset-4 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
    >
      {children}
    </a>
  )
}
