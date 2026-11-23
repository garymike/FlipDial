// Minimal hash router: #/wall, #/dial, #/map, #/review, #/contact/<uid>

export type Route =
  | { name: 'wall' }
  | { name: 'dial' }
  | { name: 'map' }
  | { name: 'review' }
  | { name: 'contact'; uid: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/')
  switch (parts[0]) {
    case 'dial':
      return { name: 'dial' }
    case 'map':
      return { name: 'map' }
    case 'review':
      return { name: 'review' }
    case 'contact':
      if (parts[1]) return { name: 'contact', uid: decodeURIComponent(parts[1]) }
      return { name: 'wall' }
    default:
      return { name: 'wall' }
  }
}

export const router = $state({ route: parse(location.hash) })

window.addEventListener('hashchange', () => {
  router.route = parse(location.hash)
  window.scrollTo(0, 0)
})

export function href(route: Route): string {
  return route.name === 'contact' ? `#/contact/${encodeURIComponent(route.uid)}` : `#/${route.name}`
}
