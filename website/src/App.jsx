import { useState, useEffect } from 'react'
import './App.css'
import Header from './components/Header'
import BuzzySidebar from './components/BuzzySidebar'
import VideoGallery from './components/VideoGallery'
import Footer from './components/Footer'
import HeroBanner from './components/HeroBanner'

const API_BASE = '/api'

function App() {
  const [videos, setVideos] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchVideos()
  }, [])

  async function fetchVideos() {
    try {
      setLoading(true)
      const res = await fetch(`${API_BASE}/videos`)
      if (!res.ok) throw new Error(`API error: ${res.status}`)
      const data = await res.json()
      setVideos(data.videos || [])
    } catch (err) {
      console.warn('API unavailable, using placeholder data:', err.message)
      setVideos(placeholderVideos)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <Header />
      <HeroBanner />
      <div className="main-layout">
        <BuzzySidebar side="left" />
        <main className="center-column">
          <VideoGallery videos={videos} loading={loading} error={error} />
        </main>
        <BuzzySidebar side="right" />
      </div>
      <Footer />
    </div>
  )
}

// Placeholder data shown when API is unreachable (pre-deploy / dev)
const placeholderVideos = [
  {
    video_id: 'demo-1',
    title: 'The Perfect Risotto — Floyd Style',
    description: 'A sumptuous risotto reimagined with a generous glass of Chianti and the unmistakable flair of Keith Floyd.',
    thumbnail: null,
    status: 'published',
    published_at: '2026-03-01T12:00:00Z',
    original_channel: '@GaryEats',
  },
  {
    video_id: 'demo-2',
    title: 'Pan-Seared Sea Bass with Wine Butter',
    description: 'Darling, this sea bass practically begs for a crisp Sancerre. Watch Keith... er... Gary give it the Floyd treatment.',
    thumbnail: null,
    status: 'published',
    published_at: '2026-02-25T15:30:00Z',
    original_channel: '@GaryEats',
  },
  {
    video_id: 'demo-3',
    title: 'Lamb Shoulder Slow Roast — A Bordeaux Affair',
    description: 'Low and slow, just like a good Bordeaux. This lamb shoulder gets the full Floyd makeover, wine glass firmly in hand.',
    thumbnail: null,
    status: 'published',
    published_at: '2026-02-20T10:00:00Z',
    original_channel: '@GaryEats',
  },
  {
    video_id: 'demo-4',
    title: 'Thai Green Curry Meets Gewürztraminer',
    description: 'An improbable pairing that Keith would have adored. Spice, coconut, and a cheeky splash of wine.',
    thumbnail: null,
    status: 'processing',
    published_at: '2026-02-18T09:00:00Z',
    original_channel: '@GaryEats',
  },
]

export default App
