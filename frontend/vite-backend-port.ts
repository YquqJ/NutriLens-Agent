const DEFAULT_BACKEND_PORT = 8000

export function resolveBackendPort(
  explicitPort: string | undefined,
  runtimePort: string | undefined,
): number {
  for (const value of [explicitPort, runtimePort]) {
    const candidate = value?.trim()
    if (candidate && /^\d+$/.test(candidate)) {
      const port = Number(candidate)
      if (port >= 1 && port <= 65535) return port
    }
  }
  return DEFAULT_BACKEND_PORT
}
