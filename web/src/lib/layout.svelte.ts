// Which layout the screen gets. Desktop is the default and is never changed by the others.
//   phone:   narrow screens (up to 700px): compact header, tab bar at the bottom, the reading
//            pane opens full screen.
//   tablet:  touch screens up to 1100px wide (an iPad held upright): the reading pane slides
//            in from the right. A narrow desktop window (mouse) keeps the desktop layout.
//   desktop: everything else, including an iPad held sideways.

export type Layout = 'phone' | 'tablet' | 'desktop'

const PHONE = '(max-width: 700px)'
const TABLET = '(max-width: 1100px) and (pointer: coarse)'

function current(): Layout {
  if (typeof window === 'undefined' || !window.matchMedia) return 'desktop'
  if (window.matchMedia(PHONE).matches) return 'phone'
  if (window.matchMedia(TABLET).matches) return 'tablet'
  return 'desktop'
}

export const layout = $state({ mode: current() as Layout })

if (typeof window !== 'undefined' && window.matchMedia) {
  for (const q of [PHONE, TABLET]) {
    window.matchMedia(q).addEventListener('change', () => (layout.mode = current()))
  }
}

/** A touch screen, where keyboard tips don't apply. */
export const touch = typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches
