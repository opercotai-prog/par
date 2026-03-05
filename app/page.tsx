'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, ChevronRight, ChevronLeft } from 'lucide-react'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export default function RentApp() {
  const [ads, setAds] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('Тюмень')
  const [activeType, setActiveType] = useState('все')

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
    <main className="min-h-screen bg-gray-100 text-gray-900 font-sans pb-10">
      {/* HEADER */}
      <header className="bg-white/80 backdrop-blur-md sticky top-0 z-30 px-4 py-3 border-b border-gray-200">
        <div className="flex justify-between items-center mb-3">
          <h1 className="text-xl font-black text-blue-600 tracking-tighter">RENT AI</h1>
          <div className="flex bg-gray-100 rounded-xl p-1 border border-gray-200">
            {['Тюмень', 'Москва'].map(c => (
              <button 
                key={c}
                onClick={() => setCity(c)}
                className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${city === c ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}
              >{c}</button>
            ))}
          </div>
        </div>

        <div className="flex gap-2 overflow-x-auto no-scrollbar">
          {['все', 'квартиры', 'студии', 'комнаты'].map((type) => (
            <button
              key={type}
              onClick={() => setActiveType(type)}
              className={`whitespace-nowrap px-4 py-2 rounded-full text-xs font-bold border transition-all ${
                activeType === type ? 'bg-gray-900 border-gray-900 text-white' : 'bg-white border-gray-200 text-gray-500'
              }`}
            >
              {type.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      {/* ADS LIST */}
      <div className="p-4 max-w-xl mx-auto space-y-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
             <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-4"></div>
             <p className="text-sm font-medium">Ищем лучшие варианты...</p>
          </div>
        ) : filteredAds.map((ad) => (
          <div key={ad.id} className="bg-white rounded-3xl shadow-xl shadow-gray-200/50 overflow-hidden border border-gray-100 group">
            
            {/* PHOTO GALLERY */}
            <div className="relative aspect-[4/3] bg-gray-200 overflow-hidden">
              <div className="flex h-full overflow-x-auto snap-x snap-mandatory no-scrollbar">
                {ad.photos && ad.photos.length > 0 ? (
                  ad.photos.map((url: string, index: number) => (
                    <div key={index} className="flex-shrink-0 w-full h-full snap-center">
                      <img 
                        src={url} 
                        alt={`Photo ${index + 1}`}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    </div>
                  ))
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-gray-100">
                    <img src={ad.main_photo_url} className="w-full h-full object-cover" />
                  </div>
                )}
              </div>
              
              {/* Photo Indicator */}
              {ad.photos && ad.photos.length > 1 && (
                <div className="absolute bottom-4 right-4 bg-black/50 backdrop-blur-md text-white px-3 py-1 rounded-full text-[10px] font-bold">
                  1 / {ad.photos.length}
                </div>
              )}

              {/* Status Badge */}
              <div className="absolute top-4 left-4">
                <span className="bg-white/90 backdrop-blur text-gray-900 text-[10px] font-black px-3 py-1.5 rounded-lg shadow-sm uppercase tracking-wider">
                  {ad.property_type === 'apartment' ? 'Квартира' : ad.property_type === 'studio' ? 'Студия' : 'Комната'}
                </span>
              </div>
            </div>

            {/* CONTENT */}
            <div className="p-5">
              <div className="flex justify-between items-end mb-4">
                <div>
                  <div className="text-3xl font-black text-gray-900 tracking-tight">
                    {ad.price_value?.toLocaleString()} <span className="text-sm font-normal text-gray-400 uppercase">/ мес</span>
                  </div>
                  {ad.deposit_value && (
                    <div className="text-[11px] text-orange-500 font-bold uppercase mt-1">
                      Залог: {ad.deposit_value} ₽
                    </div>
                  )}
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-gray-900">{ad.rooms ? `${ad.rooms}-к` : 'Студия'}</div>
                  <div className="text-[11px] text-gray-400 font-medium">{ad.area_sqm ? `${ad.area_sqm} м²` : ''}</div>
                </div>
              </div>

              <div className="flex items-start gap-2 text-gray-500 mb-6 min-h-[40px]">
                <MapPin size={16} className="text-blue-500 mt-0.5 flex-shrink-0" />
                <span className="text-sm font-medium leading-tight">{ad.address_raw || 'Адрес уточняйте у автора'}</span>
              </div>

              {/* ACTIONS */}
              <div className="grid grid-cols-2 gap-3">
                <a 
                  href={`https://t.me/${ad.contact_tg}`} 
                  className="flex items-center justify-center gap-2 bg-blue-600 text-white py-3.5 rounded-2xl font-bold text-sm active:scale-95 transition-all shadow-lg shadow-blue-200"
                >
                  <MessageCircle size={18} /> Написать
                </a>
                
                {ad.contact_phone ? (
                  <a 
                    href={`tel:${ad.contact_phone}`} 
                    className="flex items-center justify-center gap-2 bg-gray-900 text-white py-3.5 rounded-2xl font-bold text-sm active:scale-95 transition-all shadow-lg shadow-gray-300"
                  >
                    <Phone size={18} /> Позвонить
                  </a>
                ) : (
                  <a 
                    href={ad.source_url} 
                    target="_blank"
                    className="flex items-center justify-center gap-2 bg-gray-100 text-gray-600 py-3.5 rounded-2xl font-bold text-[11px] uppercase tracking-wider active:scale-95 transition-all"
                  >
                    В Telegram
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}

        {!loading && filteredAds.length === 0 && (
          <div className="text-center py-20">
            <div className="text-5xl mb-6">🏜️</div>
            <p className="text-gray-400 font-bold text-sm uppercase tracking-widest">Ничего не найдено</p>
          </div>
        )}
      </div>
    </main>
  )
}
