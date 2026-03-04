import { useState } from 'react'
import './VideoCard.css'

const STATUS_LABELS = {
  published: { text: 'Ready to Watch', color: '#4caf50', icon: '▶️' },
  processing: { text: 'Being Floyd-ified...', color: '#ff9800', icon: '🔄' },
  downloading: { text: 'Downloading', color: '#2196f3', icon: '⬇️' },
  error: { text: 'Spilt Wine', color: '#f44336', icon: '💔' },
}

export default function VideoCard({ video, index }) {
  const [hovered, setHovered] = useState(false)
  const status = STATUS_LABELS[video.status] || STATUS_LABELS.processing

  const publishDate = video.published_at
    ? new Date(video.published_at).toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      })
    : null

  return (
    <article
      className={`video-card ${hovered ? 'video-card--hovered' : ''}`}
      style={{ animationDelay: `${index * 0.12}s` }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Thumbnail / placeholder */}
      <div className="video-card-thumb">
        {video.thumbnail ? (
          <img src={video.thumbnail} alt={video.title} className="video-card-img" />
        ) : (
          <div className="video-card-placeholder">
            <span className="placeholder-icon">🍷</span>
            <span className="placeholder-text">Preview Coming Soon</span>
          </div>
        )}

        {/* Status badge */}
        <span className="video-card-status" style={{ background: status.color }}>
          {status.icon} {status.text}
        </span>

        {/* Play overlay on hover */}
        {video.status === 'published' && (
          <div className="video-card-play-overlay">
            <span className="play-btn">▶</span>
          </div>
        )}
      </div>

      {/* Card body */}
      <div className="video-card-body">
        <h3 className="video-card-title">{video.title}</h3>
        <p className="video-card-desc">{video.description}</p>
        <div className="video-card-meta">
          {publishDate && <span className="meta-date">📅 {publishDate}</span>}
          <span className="meta-source">via {video.original_channel}</span>
          <span className="meta-wine">🍷</span>
        </div>
      </div>

      {/* Shimmer effect */}
      <div className="video-card-shimmer" />
    </article>
  )
}
