import './HeroBanner.css'

export default function HeroBanner() {
  return (
    <section className="hero">
      <div className="hero-particles">
        {Array.from({ length: 20 }).map((_, i) => (
          <span
            key={i}
            className="hero-particle"
            style={{
              left: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 5}s`,
              animationDuration: `${3 + Math.random() * 4}s`,
              fontSize: `${0.8 + Math.random() * 1.2}rem`,
            }}
          >
            {['🍷', '🍇', '🥂', '🍾', '✨', '🔥'][i % 6]}
          </span>
        ))}
      </div>
      <div className="hero-content">
        <h2 className="hero-title">
          <span className="hero-line-1">Cooking Videos</span>
          <span className="hero-line-2">Reimagined</span>
          <span className="hero-line-3">in the style of <em>Keith Floyd</em></span>
        </h2>
        <p className="hero-subtitle">
          Every dish deserves a glass of wine. Every recipe deserves flair.
          <br />
          We take <strong>@GaryEats</strong> videos and transform them into
          the unmistakable style of the legendary Keith Floyd.
        </p>
        <div className="hero-cta">
          <a href="#videos" className="btn btn-primary">Watch Now 🍷</a>
          <a href="#about" className="btn btn-outline">Learn More</a>
        </div>
      </div>
      <div className="hero-wine-glass">
        <svg viewBox="0 0 120 200" className="wine-glass-svg">
          <ellipse cx="60" cy="30" rx="40" ry="28" fill="none" stroke="rgba(255,213,79,0.3)" strokeWidth="2" />
          <path d="M20,30 Q20,90 60,100 Q100,90 100,30" fill="rgba(139,34,82,0.3)" stroke="rgba(255,213,79,0.3)" strokeWidth="2" />
          <line x1="60" y1="100" x2="60" y2="160" stroke="rgba(255,213,79,0.3)" strokeWidth="2" />
          <line x1="35" y1="160" x2="85" y2="160" stroke="rgba(255,213,79,0.3)" strokeWidth="3" strokeLinecap="round" />
          <ellipse cx="60" cy="55" rx="30" ry="12" fill="rgba(139,34,82,0.5)">
            <animate attributeName="ry" values="12;14;12" dur="3s" repeatCount="indefinite" />
          </ellipse>
        </svg>
      </div>
    </section>
  )
}
