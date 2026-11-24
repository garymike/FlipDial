// Minimal hash router: #/wall, #/wall/<uid> (a contact open in the reading pane), #/dial,
// #/map, #/review, #/duplicates, #/transfer, #/activity, #/setup.
// #/contact/<uid> is the older contact page link; it opens the Wall's reading pane.
// An empty hash opens the view used last (Dial at first).

export type Route =
  | { name: 'wall'; uid?: string }
  | { name: 'dial' }
  | { name: 'map' }
  | { name: 'review' }
  | { name: 'duplicates' }
  | { name: 'transfer' }
  | { name: 'activity' }
  | { name: 'setup' }

const VIEW_KEY = 'flipdial.view'

export function lastView(): 'wall' | 'dial' {
  try {
    return localStorage.getItem(VIEW_KEY) === 'wall' ? 'wall' : 'dial'
  } catch {
    return 'dial'
  }
}

function remember(view: 'wall' | 'dial') {
  try {
    localStorage.setItem(VIEW_KEY, view)
  } catch {
    /* storage unavailable */
  }
}

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/')
  switch (parts[0]) {
    case '':
      return { name: lastView() }
    case 'wall':
      return parts[1] ? { name: 'wall', uid: decodeURIComponent(parts[1]) } : { name: 'wall' }
    case 'dial':
      return { name: 'dial' }
    case 'map':
      return { name: 'map' }
    case 'review':
      return { name: 'review' }
    case 'duplicates':
      return { name: 'duplicates' }
    case 'transfer':
      return { name: 'transfer' }
    case 'activity':
      return { name: 'activity' }
    case 'setup':
      return { name: 'setup' }
    case 'contact':
      if (parts[1]) return { name: 'wall', uid: decodeURIComponent(parts[1]) }
      return { name: 'wall' }
    default:
      return { name: 'wall' }
  }
}

export const router = $state({ route: parse(location.hash) })
if (router.route.name === 'wall' || router.route.name === 'dial') remember(router.route.name)

window.addEventListener('hashchange', () => {
  const before = router.route
  router.route = parse(location.hash)
  if (router.route.name === 'wall' || router.route.name === 'dial') remember(router.route.name)
  // Opening or closing the pane keeps the Wall where it was scrolled.
  if (!(before.name === 'wall' && router.route.name === 'wall')) window.scrollTo(0, 0)
})

export function href(route: Route): string {
  if (route.name === 'wall' && route.uid) return `#/wall/${encodeURIComponent(route.uid)}`
  return `#/${route.name}`
}

/** Link to a contact: it opens in the Wall's reading pane. */
export const contactHref = (uid: string) => href({ name: 'wall', uid })
