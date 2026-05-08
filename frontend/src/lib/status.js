export function normalizeStatus(status) {
  return String(status || '').toLowerCase()
}

export function isCompletedStatus(status) {
  return normalizeStatus(status) === 'completed' || normalizeStatus(status) === 'ready'
}
