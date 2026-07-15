// POC acts as the seeded workspace admin (no real auth in the app yet).
export const USER_ID = 1

export async function api(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}

export const getBoards = () => api(`/api/boards?user_id=${USER_ID}`)
export const getBoard = (id) => api(`/api/boards/${id}?user_id=${USER_ID}`)

// Status metadata mirrored from the vanilla app (frontend/index.html).
export const STATUS = {
  backlog: { he: 'בתכנון', c: '#9699a6' },
  todo: { he: 'לביצוע', c: '#c4c4c4' },
  in_progress: { he: 'בתהליך', c: '#fdab3d' },
  review: { he: 'בבדיקה', c: '#579bfc' },
  done: { he: 'הושלם', c: '#00c875' },
  cancelled: { he: 'בוטל', c: '#e2445c' },
}

export const PRIORITY = {
  low: { he: 'נמוכה', c: '#579bfc' },
  medium: { he: 'בינונית', c: '#5559df' },
  high: { he: 'גבוהה', c: '#fdab3d' },
  critical: { he: 'קריטית', c: '#e2445c' },
}

// Deterministic illustrated avatar from the bundled pool (same scheme as vanilla app).
function hash(s) {
  let h = 0
  for (let i = 0; i < (s || '').length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}
export function avatarUrl(user) {
  if (user && user.avatar_url) return user.avatar_url
  const seed = (user && (user.name || user.user_name)) || String(user || 'user')
  return `/avatars/${String(hash(seed) % 30).padStart(2, '0')}.svg`
}
