'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, X } from 'lucide-react'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export default function RentApp() {
  const [ads, setAds] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('Тюмень')
  const [selectedPhotos, setSelectedPhotos] = useState<string[] | null>(null)

  useEffect(() => {
    async function fetchAds() {
      setLoading(true)
      const { data } = await supabase.from('eready_ads').select('*').order('created_at', { ascending: false })
      if (data) setAds(data)
      setLoading(false)
    }
    fetchAds()
  }, [])

  const filteredAds = ads.filter(ad => (city === 'Тюмень' ? ad.channel_id === 2 : ad.channel_id === 5))

  return (
    <main className="min-h-screen bg-white text-black font-sans">
      {/* МИНИ-ШАПКА */}
      <header className="sticky top-0 z-40 bg-white border-b p-2 flex justify-between items-center px-4">
        <b className="text-blue-600 text-sm italic">RENT AI</b>
        <div className="flex bg-gray-100 rounded-md p-0.5">
          {['Тюмень', 'Москва'].map(c => (
            <button key={c} onClick={() => setCity(c)} className={`px-3 py-0.5 text-[10px] font-bold rounded ${city === c ? 'bg-white shadow text-blue-600' : 'text-gray-400'}`}>{c}</button>
          ))}
        </div>
      </header>

      {/* СПИСОК ОБЪЯВЛЕНИЙ */}
      <div className="divide-y divide-gray-100">
        {loading ? (
          <p className="p-10 text-center text-xs text-gray-400 uppercase tracking-tighter">Синхронизация...</p>
        ) : filteredAds.map((ad) => (
          <div key={ad.id} className="flex items-center p-3 gap-3 active:bg-gray-50 transition-colors">
            
            {/* ФОТО (ЖЕСТКИЙ КВАДРАТ 70px) */}
            <div 
              className="w-[70px] h-[70px] flex-shrink-0 bg-gray-100 rounded-lg overflow-hidden border border-gray-100"
              onClick={() => ad.photos && setSelectedPhotos(ad.photos)}
            >
              <img 
                src={ad.main_photo_url || (ad.photos && ad.photos[0])} 
                className="w-full h-full object-cover pointer-events-none" 
                alt="thumb" 
              />
            </div>

            {/* ИНФОРМАЦИЯ (ЦЕНТР) */}
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="font-black text-sm">{ad.price_value?.toLocaleString()} ₽</span>
                <span className="text-[9px] font-bold text-gray-400 uppercase tracking-tighter">
                   {ad.rooms ? `${ad.rooms}к` : 'студ'} • {ad.property_type === 'room' ? 'комн' : 'кв'}
                </span>
              </div>
              <div className="flex items-center gap-1 mt-1">
                <MapPin size={10} className="text-blue-500 flex-shrink-0" />
                <p className="text-[10px] text-gray-500 truncate font-medium tracking-tight">
                  {ad.address_raw || 'Адрес в ТГ'}
                </p>
              </div>
              {ad.deposit_value && <p className="text-[8px] font-bold text-orange-400 mt-1 uppercase">Залог: {ad.deposit_value}₽</p>}
            </div>

            {/* КНОПКИ (СПРАВА) */}
            <div className="flex flex-col gap-2">
              <a href={`https://t.me/${ad.contact_tg}`} className="p-2 bg-blue-50 text-blue-600 rounded-full">
                <MessageCircle size={16} />
              </a>
              {ad.contact_phone && (
                <a href={`tel:${ad.contact_phone}`} className="p-2 bg-gray-50 text-gray-900 rounded-full">
                  <Phone size={16} />
                </a>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* ГАЛЕРЕЯ НА ВЕСЬ ЭКРАН (ТОЛЬКО ПРИ КЛИКЕ) */}
      {selectedPhotos && (
        <div className="fixed inset-0 bg-black z-50 overflow-y-auto p-4 flex flex-col gap-4">
          <button onClick={() => setSelectedPhotos(null)} className="fixed top-4 right-4 bg-white/20 p-2 rounded-full text-white backdrop-blur-md">
            <X size={24} />
          </button>
          <div className="mt-12 space-y-4">
            {selectedPhotos.map((url, i) => (
              <img key={i} src={url} className="w-full rounded-xl shadow-2xl" alt="" />
            ))}
          </div>
        </div>
      )}
    </main>
  )
}
