'use client'

import { createClient } from '@supabase/supabase-js'
import { useState, useEffect } from 'react'
import { MapPin, MessageCircle, Phone, Home, Layers, User } from 'lucide-react'

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

  // Логика фильтрации
  const filteredAds = ads.filter(ad => {
    const cityMatch = city === 'Тюмень' ? ad.channel_id === 2 : ad.channel_id === 5
    const typeMatch = activeType === 'все' || 
                     (activeType === 'квартиры' && ad.property_type === 'apartment') ||
                     (activeType === 'студии' && ad.property_type === 'studio') ||
                     (activeType === 'комнаты' && (ad.property_type === 'room' || ad.property_type === 'coliving'))
    return cityMatch && typeMatch
  })

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900 font-sans">
      {/* HEADER */}
      <header className="bg-white border-b sticky top-0 z-20 px-4 py-3 shadow-sm">
        <div className="flex justify-between items-center mb-3">
          <h1 className="text-xl font-extrabold text-blue-600 tracking-tight">RENT AI</h1>
          <div className="flex bg-gray-100 rounded-lg p-1">
            <button 
              onClick={() => setCity('Тюмень')}
              className={`px-3 py-1 text-sm font-medium rounded-md transition ${city === 'Тюмень' ? 'bg-white shadow text-blue-600' : 'text-gray-500'}`}
            >Тюмень</button>
            <button 
              onClick={() => setCity('Москва')}
              className={`px-3 py-1 text-sm font-medium rounded-md transition ${city === 'Москва' ? 'bg-white shadow text-blue-600' : 'text-gray-500'}`}
            >Москва</button>
          </div>
        </div>

        {/* TYPE FILTERS */}
        <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
          {['все', 'квартиры', 'студии', 'комнаты'].map((type) => (
            <button
              key={type}
              onClick={() => setActiveType(type)}
              className={`whitespace-nowrap px-4 py-1.5 rounded-full text-sm font-medium border transition ${
                activeType === type ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-200 text-gray-600'
              }`}
            >
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>
      </header>

      {/* ADS LIST */}
      <div className="p-4 max-w-2xl mx-auto space-y-4">
        <p className="text-xs text-gray-400 font-medium px-1">НАЙДЕНО: {filteredAds.length}</p>
        
        {loading ? (
          <div className="text-center py-20 text-gray-400">Загрузка объявлений...</div>
        ) : filteredAds.length > 0 ? (
          filteredAds.map((ad) => (
            <div key={ad.id} className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden active:scale-[0.98] transition-transform">
              <div className="p-5">
                <div className="flex justify-between items-start mb-2">
                  <div className="text-2xl font-black text-gray-900">
                    {ad.price_value?.toLocaleString()} <span className="text-lg font-normal">₽/мес</span>
                  </div>
                  <div className="flex flex-col items-end">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-blue-500 bg-blue-50 px-2 py-0.5 rounded">
                      {ad.property_type === 'apartment' ? 'Квартира' : ad.property_type === 'studio' ? 'Студия' : 'Комната'}
                    </span>
                    {ad.deposit_value && <span className="text-[10px] text-gray-400 mt-1">Залог: {ad.deposit_value} ₽</span>}
                  </div>
                </div>

                <div className="flex items-center gap-1 text-gray-500 mb-4">
                  <MapPin size={14} className="text-gray-400" />
                  <span className="text-sm truncate font-medium">{ad.address_raw || 'Адрес в описании'}</span>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {ad.contact_tg && (
                    <a 
                      href={`https://t.me/${ad.contact_tg}`} 
                      className="flex items-center justify-center gap-2 bg-blue-50 text-blue-700 py-3 rounded-xl font-bold text-sm hover:bg-blue-100 transition"
                    >
                      <MessageCircle size={18} /> Написать
                    </a>
                  )}
                  {ad.contact_phone ? (
                    <a 
                      href={`tel:${ad.contact_phone}`} 
                      className="flex items-center justify-center gap-2 bg-gray-900 text-white py-3 rounded-xl font-bold text-sm hover:bg-black transition"
                    >
                      <Phone size={18} /> Позвонить
                    </a>
                  ) : (
                    <a 
                      href={ad.source_url} 
                      target="_blank"
                      className="flex items-center justify-center gap-2 bg-gray-100 text-gray-700 py-3 rounded-xl font-bold text-sm hover:bg-gray-200 transition"
                    >
                      В Telegram
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))
        ) : (
          <div className="text-center py-20">
            <div className="text-4xl mb-4">🏠</div>
            <p className="text-gray-500">В этом разделе пока пусто</p>
          </div>
        )}
      </div>
    </main>
  )
}
