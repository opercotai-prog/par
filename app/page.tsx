'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, X, Maximize2, Home, Building2, UserCircle } from 'lucide-react'

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

  // Иконка типа жилья
  const getPropIcon = (type: string) => {
    if (type === 'apartment') return <Building2 size={10} />
    if (type === 'room' || type === 'coliving') return <UserCircle size={10} />
    return <Home size={10} />
  }

  return (
    <main className="min-h-screen bg-white text-gray-900 pb-10">
      {/* HEADER - Ультра-тонкий */}
      <header className="bg-white/95 backdrop-blur sticky top-0 z-30 px-3 py-2 border-b flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="font-black text-blue-600 text-sm tracking-tighter italic">RENT AI</span>
          <div className="h-4 w-[1px] bg-gray-200"></div>
          <div className="flex bg-gray-100 rounded-md p-0.5">
            {['Тюмень', 'Москва'].map(c => (
              <button key={c} onClick={() => setCity(c)} className={`px-2 py-0.5 text-[9px] font-bold rounded ${city === c ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>{c}</button>
            ))}
          </div>
        </div>
        <div className="flex gap-1 overflow-x-auto no-scrollbar">
          {['все', 'квартиры', 'студии', 'комнаты'].map((t) => (
            <button key={t} onClick={() => setActiveType(t)} className={`px-2 py-0.5 rounded text-[9px] font-bold border transition-colors ${activeType === t ? 'bg-gray-900 border-gray-900 text-white' : 'bg-white border-gray-200 text-gray-400'}`}>{t.toUpperCase()}</button>
          ))}
        </div>
      </header>

      {/* ADS LIST */}
      <div className="max-w-2xl mx-auto divide-y divide-gray-50">
        {loading ? (
          <div className="text-center py-10 text-[10px] font-bold text-gray-300 uppercase tracking-widest animate-pulse">Синхронизация базы...</div>
        ) : filteredAds.map((ad) => (
          <div key={ad.id} className="p-3 flex gap-3 hover:bg-gray-50/50 transition-colors">
            
            {/* MINI COLLAGE (Квадрат слева) */}
            <div 
              className="relative w-24 h-24 flex-shrink-0 bg-gray-100 rounded-lg overflow-hidden border border-gray-100 cursor-pointer group"
              onClick={() => ad.photos && setSelectedPhotos(ad.photos)}
            >
              {ad.photos && ad.photos.length >= 3 ? (
                <div className="grid grid-cols-2 gap-[1px] h-full">
                  <img src={ad.photos[0]} className="h-full w-full object-cover" alt="1" />
                  <div className="grid grid-rows-2 gap-[1px] h-full">
                    <img src={ad.photos[1]} className="h-full w-full object-cover" alt="2" />
                    <img src={ad.photos[2]} className="h-full w-full object-cover" alt="3" />
                  </div>
                </div>
              ) : (
                <img src={ad.main_photo_url} className="w-full h-full object-cover" alt="single" />
              )}
              
              {/* Кнопка увеличения поверх фото */}
              <div className="absolute inset-0 bg-black/5 opacity-0 group-active:opacity-100 flex items-center justify-center transition-opacity">
                <Maximize2 size={16} className="text-white drop-shadow-md" />
              </div>
              
              {/* Счетчик фото */}
              {ad.photos && ad.photos.length > 3 && (
                <div className="absolute bottom-1 right-1 bg-black/60 text-white text-[8px] px-1 rounded-sm font-bold">
                  +{ad.photos.length - 3}
                </div>
              )}
            </div>

            {/* INFO SECTION (Справа) */}
            <div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
              <div>
                <div className="flex justify-between items-start">
                  <span className="text-base font-black text-gray-900 tracking-tight leading-none">
                    {ad.price_value?.toLocaleString()} ₽
                  </span>
                  <span className="flex items-center gap-0.5 text-[8px] font-bold text-gray-300 uppercase">
                    {getPropIcon(ad.property_type)}
                    {ad.rooms && `${ad.rooms}-к`}
                  </span>
                </div>
                
                <div className="mt-1 flex items-start gap-1 text-gray-500">
                  <MapPin size={10} className="text-blue-500 mt-0.5 flex-shrink-0" />
                  <p className="text-[11px] leading-tight font-medium line-clamp-2 italic text-gray-400">
                    {ad.address_raw || 'Адрес в описании ТГ'}
                  </p>
                </div>
              </div>

              {/* ACTION BUTTONS (Внизу справа) */}
              <div className="flex items-center justify-between mt-2">
                <div className="text-[9px] font-bold text-orange-500">
                  {ad.deposit_value ? `ЗАЛОГ: ${ad.deposit_value} ₽` : 'БЕЗ ЗАЛОГА'}
                </div>
                <div className="flex gap-1.5">
                  <a href={`https://t.me/${ad.contact_tg}`} className="p-1.5 bg-blue-50 text-blue-600 rounded-md active:bg-blue-600 active:text-white transition-all">
                    <MessageCircle size={14} />
                  </a>
                  {ad.contact_phone && (
                    <a href={`tel:${ad.contact_phone}`} className="p-1.5 bg-gray-50 text-gray-900 rounded-md active:bg-black active:text-white transition-all">
                      <Phone size={14} />
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* LIGHTBOX (Полноэкранный просмотр) */}
      {selectedPhotos && (
        <div className="fixed inset-0 bg-black/95 backdrop-blur-xl z-50 flex flex-col overflow-hidden">
          <header className="p-4 flex justify-between items-center border-b border-white/10">
            <span className="text-white text-[10px] font-bold uppercase tracking-widest">{selectedPhotos.length} ФОТО ОБЪЕКТА</span>
            <button onClick={() => setSelectedPhotos(null)} className="p-2 bg-white/10 rounded-full text-white">
              <X size={20} />
            </button>
          </header>
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-6 scroll-smooth">
            {selectedPhotos.map((src, i) => (
              <img key={i} src={src} className="w-full rounded-xl shadow-2xl border border-white/5" alt={`Photo ${i}`} />
            ))}
            <div className="h-20 flex items-center justify-center text-white/20 text-[10px] font-bold">КОНЕЦ ГАЛЕРЕИ</div>
          </div>
        </div>
      )}
    </main>
  )
}
