export interface RememberedCredentials {
  username: string
  password: string
}

const storageKey = 'nutrilens.rememberedCredentials'

export function getRememberedCredentials(): RememberedCredentials | null {
  try {
    const value = localStorage.getItem(storageKey)
    if (!value) return null

    const credentials = JSON.parse(value) as Partial<RememberedCredentials>
    if (!credentials.username || !credentials.password) return null

    return { username: credentials.username, password: credentials.password }
  } catch {
    return null
  }
}

export function saveRememberedCredentials(credentials: RememberedCredentials) {
  localStorage.setItem(storageKey, JSON.stringify(credentials))
}

export function clearRememberedCredentials() {
  localStorage.removeItem(storageKey)
}
