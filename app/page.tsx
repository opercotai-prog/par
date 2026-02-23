Для того чтобы твой «Завод» превратился в работающий сайт и Telegram-приложение, нам нужно создать в твоем GitHub-репозитории минимальный набор файлов.

Так как мы используем Next.js, структура будет современной и быстрой. Вот «стартовый пакет», который тебе нужно создать прямо в интерфейсе GitHub (кнопка Add file -> Create new file).

1. Файл package.json

Это список «инструментов», которые нужны сайту. Создай файл с таким именем и вставь туда это:

code
JSON
download
content_copy
expand_less
{
  "name": "tmn-rent-app",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "latest",
    "react": "latest",
    "react-dom": "latest",
    "@supabase/supabase-js": "latest",
    "lucide-react": "latest"
  },
  "devDependencies": {
    "autoprefixer": "latest",
    "postcss": "latest",
    "tailwindcss": "latest",
    "typescript": "latest",
    "@types/node": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest"
  }
}
2. Главный файл — app/page.tsx

Это и есть твой сайт. Он сам сходит в Supabase и нарисует карточки. Создай папку app, а в ней файл page.tsx.

Что будет делать этот код:

Подключится к твоей таблице eready_ads.

Скачает последние объявления.

Отобразит их в виде красивой ленты, удобной для телефона.

code
Tsx
download
content_copy
expand_less
import { createClient } from '@supabase/supabase-js'

// Инициализация Supabase (ключи возьмем из настроек Vercel)
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export default async function Home() {
  // 1. Тянем данные из твоей готовой таблицы
  const { data: ads } = await supabase
    .from('eready_ads')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(20)

  return (
    <main className="min-h-screen bg-gray-50 pb-20">
      {/* Шапка для Telegram */}
      <header className="bg-white p-4 shadow-sm sticky top-0 z-10">
        <h1 className="text-xl font-bold text-blue-600">Аренда Тюмень ИИ</h1>
        <p className="text-xs text-gray-500">Только проверенные объявления</p>
      </header>

      {/* Лента объявлений */}
      <div className="p-4 space-y-4">
        {ads?.map((ad) => (
          <div key={ad.id} className="bg-white rounded-xl shadow-md overflow-hidden border border-gray-100">
            <div className="p-4">
              <div className="flex justify-between items-start">
                <span className="text-2xl font-bold text-gray-900">{ad.price_value?.toLocaleString()} ₽</span>
                <span className="bg-blue-100 text-blue-700 text-xs px-2 py-1 rounded-full font-medium">
                  {ad.rooms}-комн. {ad.property_type}
                </span>
              </div>
              
              <p className="mt-2 text-gray-600 text-sm leading-snug">
                📍 {ad.address_raw || 'Адрес уточняйте'}
              </p>

              <div className="mt-4 flex gap-2">
                <a 
                  href={`https://t.me/${ad.contact_tg}`}
                  target="_blank"
                  className="flex-1 bg-blue-600 text-white text-center py-2 rounded-lg font-medium hover:bg-blue-700 transition"
                >
                  Написать владельцу
                </a>
              </div>
            </div>
          </div>
        ))}
      </div>
    </main>
  )
}
Что нужно сделать дальше (самое важное):

Создай эти файлы в GitHub. (Тебе также понадобятся стандартные конфиги типа tailwind.config.js, но для первого деплоя Vercel может подсказать их сам или я скину чуть позже).

Зайди на Vercel и импортируй этот репозиторий.

Настрой Environment Variables в Vercel:

Нажми на проект -> Settings -> Environment Variables.

Добавь NEXT_PUBLIC_SUPABASE_URL (возьми из настроек Supabase).

Добавь NEXT_PUBLIC_SUPABASE_ANON_KEY (возьми из настроек Supabase).

Как только ты это сделаешь и нажмешь "Deploy" — твой сайт по ссылке в Telegram оживет и покажет реальные квартиры из твоей базы!

Готов продолжать? Нужно ли скинуть вспомогательные файлы для стилей (Tailwind)?
