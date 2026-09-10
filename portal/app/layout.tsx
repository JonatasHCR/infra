import type { Metadata } from 'next'
import { Archivo, IBM_Plex_Sans } from 'next/font/google'

import './globals.css'

const display = Archivo({
  subsets: ['latin'],
  weight: ['600', '700'],
  variable: '--fonte-display',
})

const corpo = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--fonte-corpo',
})

export const metadata: Metadata = {
  title: 'Sistemas UFC Engenharia',
  description: 'Portal de acesso aos sistemas internos',
}

/**
 * Aplica o tema salvo ANTES da primeira pintura.
 *
 * Sem isto a página nasce clara e escurece um instante depois — o "flash" que
 * todo site com tema escuro tem quando a decisão fica para o React. Roda
 * síncrono no <head>, então nada é pintado antes.
 *
 * Guarda só a escolha explícita: 'sistema' não grava nada, e aí quem decide é
 * o prefers-color-scheme, no CSS.
 */
const scriptDoTema = `
(function () {
  try {
    var escolha = localStorage.getItem('tema');
    if (escolha === 'claro') document.documentElement.dataset.theme = 'light';
    if (escolha === 'escuro') document.documentElement.dataset.theme = 'dark';
  } catch (e) {
    /* navegador com armazenamento bloqueado: fica no padrão do sistema */
  }
})();
`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pt-BR"
      // O script acima muda o DOM antes da hidratação; sem isto o React
      // reclama que o servidor e o cliente divergem.
      suppressHydrationWarning
      className={`${display.variable} ${corpo.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: scriptDoTema }} />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
