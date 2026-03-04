import { useMemo } from 'react'
import './BuzzySidebar.css'

// Icon sets for the floating animations
const ICONS = [
  '🍷', '🍇', '🥂', '🍾', '🔥', '✨', '🧑‍🍳', '🍽️',
  '🥘', '🍝', '🧀', '🥖', '🫒', '🌶️', '🍅', '🧄',
  '🍷', '🥩', '🐟', '🦐', '🍰', '🎬', '📺', '🎭',
]

function randomBetween(min, max) {
  return min + Math.random() * (max - min)
}

export default function BuzzySidebar({ side = 'left' }) {
  // Generate a stable set of floating items
  const items = useMemo(() => {
    return Array.from({ length: 18 }).map((_, i) => {
      const goingUp = i % 2 === 0
      return {
        id: `${side}-${i}`,
        icon: ICONS[i % ICONS.length],
        size: randomBetween(1.2, 2.8),
        x: randomBetween(5, 85),
        delay: randomBetween(0, 8),
        duration: randomBetween(6, 14),
        direction: goingUp ? 'up' : 'down',
        wobble: randomBetween(10, 40),
        opacity: randomBetween(0.3, 0.8),
      }
    })
  }, [side])

  return (
    <aside className={`buzzy-sidebar buzzy-sidebar--${side}`}>
      {/* Glow strip */}
      <div className="buzzy-glow" />

      {items.map((item) => (
        <span
          key={item.id}
          className={`buzzy-icon buzzy-icon--${item.direction}`}
          style={{
            left: `${item.x}%`,
            fontSize: `${item.size}rem`,
            animationDelay: `${item.delay}s`,
            animationDuration: `${item.duration}s`,
            '--wobble': `${item.wobble}px`,
            opacity: item.opacity,
          }}
        >
          {item.icon}
        </span>
      ))}

      {/* Pulsing wine glass accent */}
      <div className="buzzy-accent">
        <span className="buzzy-accent-icon">🍷</span>
      </div>
    </aside>
  )
}
