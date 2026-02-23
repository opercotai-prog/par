import './globals.css'

export const metadata = {
  title: 'Аренда Тюмень',
  description: 'Поиск жилья с ИИ',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  )
}
