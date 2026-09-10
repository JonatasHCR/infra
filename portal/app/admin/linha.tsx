'use client'

import { useState, useTransition } from 'react'

import type { PessoaDoRealm } from '@/lib/admin'
import type { Sistema } from '@/lib/sistemas'

import { alternarGrupo } from './acoes'

/**
 * Uma linha da tabela de acessos.
 *
 * Client Component porque as caixas mudam sozinhas ao clicar (atualização
 * otimista) — esperar o servidor a cada clique faria a marcação piscar.
 * Se a action falhar, a caixa volta ao estado anterior e o motivo aparece.
 */
export function LinhaDaPessoa({
  pessoa,
  sistemas,
  ehVoce,
}: {
  pessoa: PessoaDoRealm
  sistemas: Sistema[]
  ehVoce: boolean
}) {
  const [grupos, setGrupos] = useState<string[]>(pessoa.grupos)
  const [erro, setErro] = useState<string | null>(null)
  const [pendente, iniciar] = useTransition()

  function alternar(caminho: string, marcado: boolean) {
    const anterior = grupos
    setGrupos(marcado ? [...grupos, caminho] : grupos.filter((g) => g !== caminho))
    setErro(null)

    iniciar(async () => {
      try {
        await alternarGrupo(pessoa.id, caminho, marcado)
      } catch (e) {
        setGrupos(anterior)
        setErro(e instanceof Error ? e.message : 'Não foi possível salvar.')
      }
    })
  }

  return (
    <tr className={`border-b border-hairline last:border-0 ${pendente ? 'opacity-60' : ''}`}>
      <td className="px-4 py-3">
        <div className="font-medium text-ink">
          {pessoa.nome}
          {ehVoce && <span className="ml-2 text-xs text-faint">(você)</span>}
        </div>
        <div className="text-xs text-muted">{pessoa.email}</div>
        {pessoa.aguardandoSenha && (
          <div className="mt-1 text-xs text-aviso">
            ainda não definiu a senha
          </div>
        )}
        {!pessoa.habilitado && (
          <div className="mt-1 text-xs text-brand">conta desativada</div>
        )}
        {erro && <div className="mt-1 text-xs text-brand">{erro}</div>}
      </td>

      {sistemas.map((s) => (
        <td key={s.grupo} className="px-4 py-3 text-center">
          <input
            type="checkbox"
            className="h-4 w-4 cursor-pointer accent-brand"
            checked={grupos.includes(s.grupo)}
            disabled={pendente}
            onChange={(e) => alternar(s.grupo, e.target.checked)}
            aria-label={`${pessoa.nome}: acesso a ${s.nome}`}
          />
        </td>
      ))}
    </tr>
  )
}
