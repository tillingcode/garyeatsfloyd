import './Footer.css'

export default function Footer() {
  return (
    <footer className="footer" id="about">
      <div className="footer-inner">
        <div className="footer-brand">
          <h3 className="footer-logo">🍷 Gary Eats Floyd</h3>
          <p className="footer-tagline">
            "Cooking is an art and patience a virtue...
            <br />
            Careful preparation is the secret to good food — and a good glass of wine."
          </p>
          <p className="footer-attribution">— Inspired by Keith Floyd (1943–2009)</p>
        </div>

        <div className="footer-info">
          <div className="footer-col">
            <h4>How It Works</h4>
            <ul>
              <li>We scan @GaryEats for new videos every 24 hours</li>
              <li>Each video is downloaded and processed by AI</li>
              <li>Amazon Bedrock transforms it into Keith Floyd style</li>
              <li>The result appears right here — wine glass and all</li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>The Keith Floyd Touch</h4>
            <ul>
              <li>Always holding a glass of red wine</li>
              <li>Witty, conversational presenting style</li>
              <li>Every dish paired with wine recommendations</li>
              <li>That unmistakable 80s British charm</li>
            </ul>
          </div>
        </div>

        <div className="footer-bottom">
          <p className="footer-copy">
            &copy; {new Date().getFullYear()} GaryEatsFloyd &middot; 
            Powered by AWS Lambda, Bedrock &amp; a good Bordeaux
          </p>
          <div className="footer-wine-parade">
            {['🍷', '🍇', '🥂', '🍾', '🍷'].map((icon, i) => (
              <span
                key={i}
                className="footer-wine-icon"
                style={{ animationDelay: `${i * 0.3}s` }}
              >
                {icon}
              </span>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
