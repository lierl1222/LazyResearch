import React from 'react'

export function GlassCard({ as: Component = 'section', className = '', children, ...props }) {
  return <Component className={`glass-card panel ${className}`} {...props}>{children}</Component>
}
export function GlassInput({ as: Component = 'input', className = '', ...props }) {
  return <Component className={`glass-input ${className}`} {...props} />
}
export function GlassButton({ as: Component = 'button', className = '', ...props }) {
  return <Component className={`glass-button ${className}`} {...props} />
}
export function ResearchMark() {
  return <svg className="research-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true">
    <path d="M20 6C30 6 34 17 27 24S9 27 9 19 19 8 25 14 28 32 19 34" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <path d="M13 8C5 14 7 28 17 29S31 18 24 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><circle cx="20" cy="20" r="2" fill="currentColor" />
  </svg>
}

// Broad folds share one light direction. A small feather softens only the silhouettes.
export function OrganicBackground() {
  return <div className="organic-background" aria-hidden="true">
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="satin-front" x1="0" y1="0" x2=".36" y2="1">
          <stop stopColor="#f8f5ef" />
          <stop offset=".25" stopColor="#efeeea" />
          <stop offset=".48" stopColor="#d4d7d7" />
          <stop offset=".65" stopColor="#c3cacb" />
          <stop offset=".84" stopColor="#e4e5e2" />
          <stop offset="1" stopColor="#f4f1ea" />
        </linearGradient>
        <linearGradient id="satin-reverse" x1=".1" y1="0" x2=".74" y2="1">
          <stop stopColor="#e2e3e0" />
          <stop offset=".32" stopColor="#f7f4ee" />
          <stop offset=".62" stopColor="#dcdfde" />
          <stop offset=".83" stopColor="#c8cece" />
          <stop offset="1" stopColor="#e7e8e4" />
        </linearGradient>
        <filter id="satin-contour" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>
      <g filter="url(#satin-contour)">
        <path fill="url(#satin-reverse)" opacity=".69"
          d="M-180 775 C180 706 404 1026 802 797 S1315 248 1740 232 L1740 382 C1316 415 1212 780 847 913 S162 827 -180 940 Z" />
        <path fill="url(#satin-front)"
          d="M-160 355 C110 603 390 625 652 308 S1136 133 1322 302 S1565 407 1760 285 L1760 499 C1522 630 1336 450 1177 322 S886 191 704 438 S251 845 -160 562 Z" />
        <path fill="url(#satin-reverse)" opacity=".64"
          d="M-130 365 C155 655 428 629 670 316 S1111 161 1276 287 C1074 126 918 109 669 353 S295 762 -130 458 Z" />
      </g>
    </svg>
  </div>
}
