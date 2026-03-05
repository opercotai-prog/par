'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, X, ChevronLeft, ChevronRight } from 'lucide-react'

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
    <main className="min-h-screen bg-gray-50 text-gray-900 pb-10">
      {/* HEADER - Сделали тоньше */}
      <header className="bg-white sticky top-0 z-30 px-4 py-2 border-b flex flex-col gap-2 shadow-sm">
        <div className="flex justify-between items-center">
          <span className="font-black text-blue-600">RENT AI</span>
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            {['Тюмень', 'Москва'].map(c => (
              <button key={c} onClick={() => setCity(c)} className={`px-3 py-1 text-[10px] font-bold rounded-md ${city === c ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>{c}</button>
            ))}
          </div>
        </div>
        <div className="flex gap-1 overflow-x-auto no-scrollbar">
          {['все', 'квартиры', 'студии', 'комнаты'].map((t) => (
            <button key={t} onClick={() => setActiveType(t)} className={`px-3 py-1 rounded-full text-[10px] font-bold border ${activeType === t ? 'bg-gray-900 text-white' : 'bg-white text-gray-500'}`}>{t.toUpperCase()}</button>
          ))}
        </div>
      </header>

      {/* ADS LIST */}
      <div className="p-2 max-w-xl mx-auto space-y-2">
        {loading ? (
          <div className="text-center py-10 text-xs font-bold text-gray-400 uppercase tracking-widest">Загрузка...</div>
        ) : filteredAds.map((ad) => (
          <div key={ad.id} className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden flex flex-col">
            
            {/* PHOTO SECTION (COLLAGE) - В 3 раза меньше */}
            <div 
              className="relative h-36 bg-gray-100 cursor-pointer overflow-hidden"
              onClick={() => ad.photos && setSelectedPhotos(ad.photos)}
            >
              {ad.photos && ad.photos.length >= 3 ? (
                <div className="grid grid-cols-3 gap-0.5 h-full">
                  <img src={ad.photos[0]} className="col-span-2 h-full w-full object-cover" alt="main" />
                  <div className="flex flex-col gap-0.5 h-full">
                    <img src={ad.photos[1]} className="h-1/2 w-full object-cover" alt="2" />
                    <img src={ad.photos[2]} className="h-1/2 w-full object-cover" alt="3" />
                  </div>
                </div>
              ) : (
                <img src={ad.main_photo_url} className="w-full h-full object-cover" alt="single" />
              )}
              
              <div className="absolute top-2 left-2 bg-black/60 text-white text-[9px] px-2 py-0.5 rounded font-bold uppercase">
                {ad.property_type}
              </div>
              {ad.photos && ad.photos.length > 3 && (
                <div className="absolute bottom-2 right-2 bg-white/90 text-gray-900 text-[9px] px-2 py-0.5 rounded font-bold">
                  +{ad.photos.length - 3} фото
                </div>
              )}
            </div>

            {/* INFO SECTION - Компактная */}
            <div className="p-3 flex justify-between items-center gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-lg font-black text-gray-900">{ad.price_value?.toLocaleString()} ₽</span>
                  {ad.rooms && <span className="text-[10px] font-bold text-gray-400">{ad.rooms}-к</span>}
                </div>
                <div className="flex items-center gap-1 text-gray-500 text-[11px] truncate mt-0.5">
                  <MapPin size={10} className="text-blue-500 flex-shrink-0" />
                  <span className="truncate font-medium">{ad.address_raw || 'Адрес в ТГ'}</span>
                </div>
              </div>

              <div className="flex gap-1">
                <a href={`https://t.me/${ad.contact_tg}`} className="p-2.5 bg-blue-600 text-white rounded-lg shadow-md active:scale-90 transition-transform">
                  <MessageCircle size={16} />
                </a>
                {ad.contact_phone && (
                  <a href={`tel:${ad.contact_phone}`} className="p-2.5 bg-gray-900 text-white rounded-lg shadow-md active:scale-90 transition-transform">
                    <Phone size={16} />
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* LIGHTBOX (Увеличение при нажатии) */}
      {selectedPhotos && (
        <div className="fixed inset-0 bg-black z-50 flex flex-col">
          <button onClick={() => setSelectedPhotos(null)} className="absolute top-4 right-4 z-50 p-2 bg-white/10 rounded-full text-white">
            <X size={24} />
          </button>
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4 justify-center">
            {selectedPhotos.map((src, i) => (
              <img key={i} src={src} className="w-full rounded-lg shadow-2xl" alt={`Full ${i}`} />
            ))}
          </div>
        </div>
      )}
    </main>
  )
}
