import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export default async function Home() {
  const { data: ads } = await supabase
    .from('eready_ads')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(20)

  return (
    <main className="min-h-screen bg-gray-50 pb-20 font-sans">
      <header className="bg-white p-4 shadow-sm sticky top-0 z-10 text-center">
        <h1 className="text-xl font-bold text-blue-600">Аренда Тюмень</h1>
        <p className="text-xs text-gray-500 font-medium">Объявления от ИИ-модератора</p>
      </header>

      <div className="p-4 space-y-4 max-w-md mx-auto">
        {ads?.length === 0 && <p className="text-center text-gray-400 mt-10">Объявлений пока нет...</p>}
        
        {ads?.map((ad) => (
          <div key={ad.id} className="bg-white rounded-2xl shadow-sm overflow-hidden border border-gray-100 p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-2xl font-black text-gray-900">
                {ad.price_value ? `${ad.price_value.toLocaleString()} ₽` : 'Цена не указана'}
              </span>
              <div className="bg-blue-50 text-blue-600 text-[10px] uppercase tracking-wider px-2 py-1 rounded-lg font-bold">
                {ad.rooms}-комн.
              </div>
            </div>
            
            <p className="text-gray-600 text-sm mb-4 leading-relaxed">
              📍 {ad.address_raw || 'Адрес в описании'}
            </p>

            <div className="flex flex-col gap-2">
              {ad.contact_tg && (
                <a 
                  href={`https://t.me/${ad.contact_tg}`}
                  target="_blank"
                  className="w-full bg-blue-600 text-white text-center py-3 rounded-xl font-bold text-sm active:scale-95 transition-transform"
                >
                  Написать в Telegram
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </main>
  )
}
