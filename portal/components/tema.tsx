'use client'

import { useEffect, useState } from 'react'

type Tema = 'sistema' | 'claro' | 'escuro'

const CICLO: Record<Tema, Tema> = {
  sistema: 'claro',
  claro: 'escuro',
  escuro: 'sistema',
}

const RÓTULO: Record<Tema, string> = {
  sistema: 'Tema do sistema',
  claro: 'Tema claro',
  escuro: 'Tema escuro',
}

/**
 * Alterna entre claro, escuro e o padrão do sistema.
 *
 * Três estados, e não dois, porque "seguir o sistema" é uma escolha legítima —
 * quem deixa o computador trocar sozinho ao anoitecer perderia isso num botão
 * de duas posições, sem jeito de voltar.
 *
 * A escolha vive no `localStorage` desta pessoa, neste navegador. É preferência
 * de exibição, não dado da conta: não precisa viajar até o servidor, e é
 * aplicada antes da primeira pintura pelo script no layout.
 */
export function AlternadorDeTema() {
  const [tema, setTema] = useState<Tema>('sistema')
  const [montado, setMontado] = useState(false)

  useEffect(() => {
    try {
      const salvo = localStorage.getItem('tema')
      if (salvo === 'claro' || salvo === 'escuro') setTema(salvo)
    } catch {
      /* armazenamento bloqueado: segue no padrão do sistema */
    }
    setMontado(true)
  }, [])

  function alternar() {
    const proximo = CICLO[tema]
    setTema(proximo)

    try {
      if (proximo === 'sistema') {
        localStorage.removeItem('tema')
        delete document.documentElement.dataset.theme
      } else {
        localStorage.setItem('tema', proximo)
        document.documentElement.dataset.theme =
          proximo === 'escuro' ? 'dark' : 'light'
      }
    } catch {
      /* sem armazenamento, a escolha vale só nesta navegação */
    }
  }

  return (
    <button
      type="button"
      onClick={alternar}
      title={`${RÓTULO[tema]} — clique para ${RÓTULO[CICLO[tema]].toLowerCase()}`}
      aria-label={`${RÓTULO[tema]}. Trocar para ${RÓTULO[CICLO[tema]].toLowerCase()}`}
      className="flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
    >
      {/* Antes de montar não dá para saber o tema salvo; o ícone neutro evita
          desenhar o sol e trocar para a lua um instante depois. */}
      {!montado ? <IconeSistema /> : null}
      {montado && tema === 'sistema' ? <IconeSistema /> : null}
      {montado && tema === 'claro' ? <IconeSol /> : null}
      {montado && tema === 'escuro' ? <IconeLua /> : null}
    </button>
  )
}

const traço = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

function IconeSol() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" {...traço}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

function IconeLua() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" {...traço}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  )
}

/** Metade clara, metade escura — "o que o sistema mandar". */
function IconeSistema() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" {...traço}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none" />
    </svg>
  )
}
