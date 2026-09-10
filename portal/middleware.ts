import { NextResponse, type NextRequest } from 'next/server'

import { renovar, verificar } from '@/lib/oidc'
import {
  gravarSessao,
  lerSessao,
  limparSessao,
  sessaoDeClaims,
  type Sessao,
} from '@/lib/session'

/**
 * Protege as rotas e RENOVA o token quando ele esta perto de vencer.
 *
 * O refresh precisa acontecer aqui, e nao na pagina: um Server Component nao
 * pode gravar cookie, entao ele conseguiria renovar o token mas nao guardar o
 * resultado — e a renovacao se repetiria a cada request. O middleware e o unico
 * ponto do Next que le a sessao e escreve na resposta.
 */

const MARGEM_SEGUNDOS = 60

function paraLogin(req: NextRequest): NextResponse {
  const login = new URL('/api/auth/login', req.url)
  const destino = req.nextUrl.pathname + req.nextUrl.search
  if (destino !== '/') login.searchParams.set('destino', destino)

  const resposta = NextResponse.redirect(login)
  limparSessao(resposta)
  return resposta
}

export async function middleware(req: NextRequest) {
  const sessao = await lerSessao(req.cookies)
  if (!sessao) return paraLogin(req)

  const agora = Math.floor(Date.now() / 1000)
  if (sessao.expires_at - MARGEM_SEGUNDOS > agora) {
    return NextResponse.next()
  }

  if (!sessao.refresh_token) return paraLogin(req)

  try {
    const tokens = await renovar(sessao.refresh_token)
    if (!tokens.id_token) throw new Error('refresh sem id_token')

    const claims = await verificar(tokens.id_token)
    // Os grupos vem do token novo: tirar alguem de um grupo no Keycloak
    // reflete aqui na renovacao seguinte, sem precisar deslogar.
    const renovada: Sessao = sessaoDeClaims(claims as Record<string, unknown>, tokens)

    const resposta = NextResponse.next()
    await gravarSessao(resposta, renovada)
    return resposta
  } catch (e) {
    // Refresh token expirado ou sessao encerrada no Keycloak (logout em outro
    // sistema). Nao e erro: e hora de logar de novo.
    console.error('[middleware] refresh falhou:', e)
    return paraLogin(req)
  }
}

export const config = {
  // Deixa passar as rotas de auth (senao o redirect para /api/auth/login
  // entraria em loop), os estaticos do Next e qualquer arquivo com extensao.
  matcher: ['/((?!api/auth|_next/static|_next/image|favicon.ico|.*\\..*).*)'],
}
