'use client'

import { useRef, useState, useTransition } from 'react'

import type { Sistema } from '@/lib/sistemas'

import { convidarPessoa } from './acoes'

/**
 * Cria a pessoa no Keycloak sem sair do portal.
 *
 * Ela nasce **sem senha**, com UPDATE_PASSWORD obrigatório — a mesma regra da
 * importação inicial. Não há senha provisória para combinar por telefone nem
 * para alguém esquecer de trocar.
 */
export function FormularioDeConvite({ sistemas }: { sistemas: Sistema[] }) {
  const [aberto, setAberto] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [pendente, iniciar] = useTransition()
  const form = useRef<HTMLFormElement>(null)

  function enviar(dados: FormData) {
    setErro(null)
    setOk(null)
    iniciar(async () => {
      try {
        await convidarPessoa(dados)
        setOk(
          `${dados.get('email')} foi criada. Ela define a senha no primeiro acesso.`,
        )
        form.current?.reset()
      } catch (e) {
        setErro(e instanceof Error ? e.message : 'Não foi possível criar.')
      }
    })
  }

  if (!aberto) {
    return (
      <div>
        <button
          onClick={() => setAberto(true)}
          className="rounded-lg border border-hairline bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-sunken"
        >
          Adicionar pessoa
        </button>
        {ok && <p className="mt-3 text-sm text-muted">{ok}</p>}
      </div>
    )
  }

  return (
    <form
      ref={form}
      action={enviar}
      className="rounded border border-hairline border-l-[3px] border-l-brand bg-surface p-5"
    >
      <h2 className="font-display font-semibold text-ink">Adicionar pessoa</h2>
      <p className="mt-1 text-sm text-muted">
        Ela vai receber acesso aos sistemas marcados e definir a senha no
        primeiro login.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-ink">Nome</span>
          <input
            name="nome"
            required
            placeholder="Maria Souza"
            className="mt-1 w-full rounded border border-hairline bg-ground px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-ink">E-mail</span>
          <input
            name="email"
            type="email"
            required
            placeholder="maria@ufcengenharia.com.br"
            className="mt-1 w-full rounded border border-hairline bg-ground px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none"
          />
        </label>
      </div>

      <fieldset className="mt-4">
        <legend className="text-sm font-medium text-ink">Acesso a</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          {sistemas.map((s) => (
            <label key={s.grupo} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="grupos"
                value={s.grupo}
                className="h-4 w-4 accent-brand"
              />
              {s.nome}
            </label>
          ))}
        </div>
      </fieldset>

      {erro && <p className="mt-4 text-sm text-brand">{erro}</p>}

      <div className="mt-5 flex gap-2">
        <button
          type="submit"
          disabled={pendente}
          className="rounded bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {pendente ? 'Criando…' : 'Criar'}
        </button>
        <button
          type="button"
          onClick={() => setAberto(false)}
          className="rounded border border-hairline px-4 py-2 text-sm text-muted transition-colors hover:bg-sunken"
        >
          Cancelar
        </button>
      </div>
    </form>
  )
}
