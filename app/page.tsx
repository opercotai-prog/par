'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, X, Maximize2 } from 'lucide-react'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export default function RentApp() {
  const [ads, setAds] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('Тюмень')
  const [activeType, setActiveType] = useState('все')
  const [selectedPhotos, setSelectedPhotos] = useState<string[] | null>(null)

  useEffect(() => {
    async function fetchAds() {
      setLoading(true)
      const { data } = await supabase
        .from('eready_ads')
        .select('*')
        .order('created_at', { ascending: false })
      if (data) setAds(data)
      setLoading(false)
    }
    fetchAds()
  }, [])

  const filteredAds = ads.filter(ad => {
    const cityMatch = city === 'Тюмень' ? ad.channel_id === 2 : ad.channel_id === 5
    const typeMatch = activeType === 'все' || 
                     (activeType === 'квартиры' && ad.property_type === 'apartment') ||
                     (activeType === 'студии' && ad.property_type === 'studio') ||
                     (activeType === 'комнаты' && (ad.property_type === 'room' || ad.property_type === 'coliving'))
    return cityMatch && typeMatch
  })

  return (
    <main className="min-h-screen bg-white text-gray-900 pb-10">
      {/* HEADER - Ультра-компактный */}
      <header className="bg-white border-b sticky top-0 z-30 px-3 py-1.5 flex items-center justify-between">
        <span className="font-black text-blue-600 text-xs tracking-tighter">RENT AI</span>
        <div className="flex gap-1 overflow-x-auto no-scrollbar max-w-[70%]">
          {['Тюмень', 'Москва'].map(c => (
            <button key={c} onClick={() => setCity(c)} className={`px-2 py-1 text-[9px] font-bold rounded ${city === c ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-400'}`}>{c}</button>
          ))}
          <div className="w-[1px] bg-gray-200 mx-1"></div>
          {['все', 'квартиры', 'студии', 'комнаты'].map((t) => (
            <button key={t} onClick={() => setActiveType(t)} className={`px-2 py-1 rounded text-[9px] font-bold ${activeType === t ? 'bg-gray-900 text-white' : 'bg-white text-gray-400'}`}>{t.toUpperCase()}</button>
          ))}
        </div>
      </header>

      {/* ADS LIST - Ультра-плотный список */}
      <div className="divide-y divide-gray-100">
        {loading ? (
          <div className="p-10 text-center text-[10px] text-gray-300 font-bold uppercase tracking-widest">Загрузка базы...</div>
        ) : filteredAds.map((ad) => (
          <div key={ad.id} className="p-2 flex items-center gap-3 active:bg-gray-50 transition-colors">
            
            {/* ФОТО СЛЕВА - Строго 80x80 */}
            <div 
              className="relative w-20 h-20 flex-shrink-0 rounded-lg overflow-hidden bg-gray-100 border border-gray-50 cursor-pointer"
              onClick={() => ad.photos && setSelectedPhotos(ad.photos)}
            >
              <img 
                src={ad.main_photo_url || (ad.photos && ad.photos[0])} 
                className="w-full h-full object-cover" 
                alt="flat" 
              />
              {ad.photos && ad.photos.length > 1 && (
                <div className="absolute bottom-1 right-1 bg-black/50 text-[8px] text-white px-1 rounded font-bold">
                  {ad.photos.length}
                </div>
              )}
              <div className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 bg-black/10 transition-opacity">
                <Maximize2 size={12} className="text-white" />
              </div>
            </div>

            {/* ТЕКСТ И КНОПКИ СПРАВА */}
            <div className="flex-1 min-w-0 pr-1">
              <div className="flex justify-between items-start">
                <div className="text-sm font-black text-gray-900 tracking-tight">
                  {ad.price_value?.toLocaleString()} ₽
                </div>
                <div className="text-[9px] font-bold text-gray-300 uppercase">
                  {ad.rooms ? `${ad.rooms}-к` : 'студия'}
                </div>
              </div>

              <div className="flex items-center gap-1 mt-0.5">
                <MapPin size={10} className="text-blue-500 flex-shrink-0" />
                <p className="text-[10px] text-gray-400 truncate font-medium tracking-tight">
                  {ad.address_raw || 'Адрес уточняйте'}
                </p>
              </div>

              <div className="mt-2 flex items-center justify-between">
                <span className="text-[9px] font-bold text-orange-400">
                   {ad.deposit_value ? `ЗАЛОГ ${ad.deposit_value}₽` : 'БЕЗ ЗАЛОГА'}
                </span>
                <div className="flex gap-2">
                  <a href={`https://t.me/${ad.contact_tg}`} className="w-7 h-7 flex items-center justify-center bg-blue-50 text-blue-600 rounded-md">
                    <MessageCircle size={14} />
                  </a>
                  {ad.contact_phone && (
                    <a href={`tel:${ad.contact_phone}`} className="w-7 h-7 flex items-center justify-center bg-gray-50 text-gray-900 rounded-md">
                      <Phone size={14} />
                    </a>
                  )}
                </div>
              </div>
            </div>

          </div>
        ))}
      </div>

      {/* ПОЛНОЭКРАННАЯ ГАЛЕРЕЯ (Только по клику) */}
      {selectedPhotos && (
        <div className="fixed inset-0 bg-black z-50 flex flex-col animate-in fade-in duration-200">
          <div className="p-4 flex justify-between items-center border-b border-white/10">
            <span className="text-white text-[10px] font-bold uppercase tracking-widest">Просмотр фото</span>
            <button onClick={() => setSelectedPhotos(null)} className="p-1.5 bg-white/10 rounded-full text-white">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {selectedPhotos.map((src, i) => (
              <img key={i} src={src} className="w-full rounded-xl shadow-lg border border-white/5" alt="" />
            ))}
          </div>
        </div>
      )}
    </main>
  )
}
