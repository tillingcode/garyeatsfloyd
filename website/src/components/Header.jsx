import './Header.css'

export default function Header() {
  return (
    <header className="header">
      <div className="header-inner">
        <div className="header-logo">
          <span className="logo-icon">🍷</span>
          <h1 className="logo-text">
            Gary Eats <span className="logo-accent">Floyd</span>
          </h1>
        </div>
        <nav className="header-nav">
          <a href="#videos" className="nav-link">Videos</a>
          <a href="#about" className="nav-link">About</a>
          <span className="nav-badge pulse">LIVE</span>
        </nav>
      </div>
    </header>
  )
}
