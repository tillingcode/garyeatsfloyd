import './VideoGallery.css'
import VideoCard from './VideoCard'

export default function VideoGallery({ videos, loading, error }) {
  return (
    <section className="gallery" id="videos">
      <div className="gallery-header">
        <h2 className="gallery-title">
          <span className="gallery-icon">🎬</span>
          Latest Floyd-ified Videos
        </h2>
        <p className="gallery-subtitle">
          Fresh from the kitchen — each video transformed with the spirit of Keith Floyd, 
          a generous pour of red wine, and an irrepressible love of good food.
        </p>
      </div>

      {loading && (
        <div className="gallery-loading">
          <div className="wine-loader">
            <span className="wine-loader-glass">🍷</span>
            <p>Decanting the latest videos...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="gallery-error">
          <p>Something went wrong — perhaps we've had too much wine.</p>
          <p className="gallery-error-detail">{error}</p>
        </div>
      )}

      {!loading && !error && videos.length === 0 && (
        <div className="gallery-empty">
          <span className="gallery-empty-icon">🍇</span>
          <p>No videos yet — the kitchen is warming up. Check back soon!</p>
        </div>
      )}

      {!loading && videos.length > 0 && (
        <div className="gallery-grid">
          {videos.map((video, index) => (
            <VideoCard key={video.video_id} video={video} index={index} />
          ))}
        </div>
      )}
    </section>
  )
}
