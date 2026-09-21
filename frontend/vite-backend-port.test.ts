import { describe, expect, it } from 'vitest'
import { resolveBackendPort } from './vite-backend-port'

describe('resolveBackendPort', () => {
  it('prefers an explicit BACKEND_PORT', () => {
    expect(resolveBackendPort('9000', '8001\n')).toBe(9000)
  })

  it('uses the backend runtime port when no explicit override exists', () => {
    expect(resolveBackendPort(undefined, '8001\n')).toBe(8001)
  })

  it('falls back to 8000 when neither value is valid', () => {
    expect(resolveBackendPort('invalid', 'not-a-port')).toBe(8000)
  })
})
