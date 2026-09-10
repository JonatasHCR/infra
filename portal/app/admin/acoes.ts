'use server'

import { cookies } from 'next/headers'
import { revalidatePath } from 'next/cache'

import {
  GRUPO_ADMIN,
  convidar,
  entrarNoGrupo,
  grupos,
  sairDoGrupo,
} from '@/lib/admin'
import { COOKIE_SESSAO, lerSessao } from '@/lib/session'

/**
 * Server Actions da tela de administração.
 *
 * Cada uma revalida a permissão por conta própria. Não basta a página ter
 * escondido o formulário: uma Server Action é um endpoint HTTP como qualquer
 * outro, e quem souber o id da action pode chamá-la direto.
 */

async function exigirAdmin() {
  const sessao = await lerSessao(await cookies())
  if (!sessao?.groups?.includes(GRUPO_ADMIN)) {
    throw new Error('Sem permissão para administrar acessos.')
  }
  return sessao
}

export async function alternarGrupo(
  usuarioId: string,
  caminhoGrupo: string,
  passaAPertencer: boolean,
) {
  await exigirAdmin()

  const mapa = await grupos()
  const grupoId = mapa[caminhoGrupo]
  if (!grupoId) throw new Error(`Grupo desconhecido: ${caminhoGrupo}`)

  if (passaAPertencer) {
    await entrarNoGrupo(usuarioId, grupoId)
  } else {
    await sairDoGrupo(usuarioId, grupoId)
  }

  revalidatePath('/admin')
}

export async function convidarPessoa(dadosDoFormulario: FormData) {
  await exigirAdmin()

  const email = String(dadosDoFormulario.get('email') ?? '').trim().toLowerCase()
  const nome = String(dadosDoFormulario.get('nome') ?? '').trim()
  const escolhidos = dadosDoFormulario.getAll('grupos').map(String)

  if (!email || !nome) {
    throw new Error('Nome e email são obrigatórios.')
  }

  await convidar({ email, nome, grupos: escolhidos })
  revalidatePath('/admin')
}
