import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { GRUPO_ADMIN, pessoas } from '@/lib/admin'
import { AlternadorDeTema } from '@/components/tema'
import { lerSessao } from '@/lib/session'
import { sistemas } from '@/lib/sistemas'

import { LinhaDaPessoa } from './linha'
import { FormularioDeConvite } from './convite'

/**
 * Administração de acessos.
 *
 * Faz o que o console do Keycloak já fazia (Users → Groups → Join), mas com só
 * as três caixas que interessam, em português, e sem a pessoa precisar aprender
 * outra ferramenta.
 *
 * Quem entra aqui pertence ao grupo `/admins`. A verificação está NESTA página e
 * TAMBÉM em cada Server Action — esconder o formulário não protege nada, porque
 * uma action é um endpoint como qualquer outro.
 */

export const dynamic = 'force-dynamic'

export default async function AdminPage() {
  const sessao = await lerSessao(await cookies())
  if (!sessao?.groups?.includes(GRUPO_ADMIN)) {
    redirect('/')
  }

  const lista = await pessoas()
  const apps = sistemas()

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col px-6 py-14">
      <header className="mb-8">
        <div className="flex items-start justify-between gap-4">
          <a
            href="/"
            className="text-sm text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
          >
            ← Voltar aos sistemas
          </a>
          <AlternadorDeTema />
        </div>
        <h1 className="mt-3 font-display text-2xl font-bold tracking-tight text-ink">
          Acessos
        </h1>
        <p className="mt-1 text-sm text-muted">
          Marque a que sistemas cada pessoa tem acesso. A mudança vale no próximo
          login dela, ou em até uma hora.
        </p>
      </header>

      <FormularioDeConvite sistemas={apps} />

      <div className="mt-8 overflow-x-auto rounded border border-hairline bg-surface">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-xs uppercase tracking-wide text-faint">
              <th className="px-4 py-3 font-medium">Pessoa</th>
              {apps.map((s) => (
                <th key={s.grupo} className="px-4 py-3 text-center font-medium">
                  {s.nome}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lista.length === 0 && (
              <tr>
                <td
                  colSpan={apps.length + 1}
                  className="px-4 py-8 text-center text-muted"
                >
                  Nenhuma pessoa no realm ainda. Use o formulário acima, ou o
                  script de importação em <code>infra/scripts/import_users.py</code>.
                </td>
              </tr>
            )}
            {lista.map((pessoa) => (
              <LinhaDaPessoa
                key={pessoa.id}
                pessoa={pessoa}
                sistemas={apps}
                ehVoce={pessoa.email === sessao.email}
              />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-faint">
        {lista.length} pessoa(s). Quem administra os acessos pertence ao grupo{' '}
        <code>/admins</code>, que só se concede pelo console do Keycloak — de
        propósito: assim ninguém se promove a administrador por esta tela.
      </p>
    </main>
  )
}
