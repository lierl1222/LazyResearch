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

// Static, original silver ribbons sit below three blurred container surfaces.
export function OrganicBackground() {
  return <div className="organic-background" aria-hidden="true"><svg viewBox="0 0 1600 1100" preserveAspectRatio="xMidYMid slice">
    <defs>
      <linearGradient id="silver" x1="0" x2="1" y1="0" y2=".8"><stop stopColor="#fff"/><stop offset=".24" stopColor="#c4cbc6"/><stop offset=".43" stopColor="#fdfefd"/><stop offset=".53" stopColor="#aeb8b1"/><stop offset=".65" stopColor="#fff"/><stop offset=".86" stopColor="#d0d6d1"/><stop offset="1" stopColor="#fafbf9"/></linearGradient>
      <linearGradient id="edge" x1="0" x2="1"><stop stopColor="#fff"/><stop offset=".5" stopColor="#b5beb6"/><stop offset="1" stopColor="#fff"/></linearGradient>
      <linearGradient id="fold-metal" gradientUnits="userSpaceOnUse" x1="585" y1="310" x2="755" y2="590">
        <stop stopColor="#e5e9e8" />
        <stop offset=".22" stopColor="#fbfcfb" />
        <stop offset=".37" stopColor="#cbd2d2" />
        <stop offset=".53" stopColor="#889699" />
        <stop offset=".62" stopColor="#e2e7e6" />
        <stop offset=".72" stopColor="#ffffff" />
        <stop offset="1" stopColor="#abb7b8" />
      </linearGradient>
      <linearGradient id="fold-return" gradientUnits="userSpaceOnUse" x1="850" y1="440" x2="1230" y2="735">
        <stop stopColor="#fbfcfb" />
        <stop offset=".32" stopColor="#adb8b8" />
        <stop offset=".49" stopColor="#8a999c" />
        <stop offset=".63" stopColor="#e9edec" />
        <stop offset=".76" stopColor="#fff" />
        <stop offset="1" stopColor="#c0c9c8" />
      </linearGradient>
    </defs>
    <g fill="none" strokeLinecap="round">
      <path d="M-200 950C140 910 125 610 400 620S640 950 930 830 1100 100 1800 160" stroke="url(#silver)" strokeWidth="125" opacity=".65"/>
      <path d="M-200 910C140 870 125 570 400 580S640 910 930 790 1100 60 1800 120" stroke="url(#edge)" strokeWidth="2" opacity=".8"/>
      <path d="M500-180C270 110 650 270 1000 150S1210 350 1700 450" stroke="url(#silver)" strokeWidth="90" opacity=".5"/>
      <path d="M500-150C270 140 650 300 1000 180S1210 380 1700 480" stroke="white" strokeWidth="2" opacity=".9"/>
      <path d="M-100 330C220 100 560 360 510 640S840 1120 1350 1040" stroke="url(#edge)" strokeWidth="3" opacity=".38"/>
    </g>
    {/* Two faces of one folded ribbon cross behind the task, workflow and metrics panels. */}
    <g>
      <path fill="url(#fold-metal)" d="M-120 430 C185 638 332 602 555 436 C739 298 850 270 987 377 C844 322 761 402 616 525 C355 747 92 759 -120 612 Z" />
      <path fill="url(#fold-return)" d="M987 377 C1083 418 1094 609 1246 642 C1371 668 1510 587 1700 438 L1700 610 C1518 765 1354 825 1190 712 C1035 604 1057 424 987 377 Z" />
      <path fill="none" stroke="#ffffffde" strokeWidth="2.2" d="M-120 430 C185 638 332 602 555 436 C739 298 850 270 987 377 C1083 418 1094 609 1246 642 C1371 668 1510 587 1700 438" />
      <path fill="none" stroke="#6d7e821f" strokeWidth="3" d="M-120 612 C92 759 355 747 616 525 C761 402 844 322 987 377" />
    </g>
  </svg></div>
}
