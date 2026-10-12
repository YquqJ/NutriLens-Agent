import { describe, expect, it } from 'vitest'
import { appendAgentName, appendAgentNames } from './labels'

describe('agent label aggregation', () => {
  it('keeps every participating agent in first-seen order', () => {
    let names: string[] = []
    names = appendAgentName(names, 'diet_agent')
    names = appendAgentName(names, 'exercise_agent')
    names = appendAgentName(names, 'diet_agent')

    expect(names).toEqual(['diet_agent', 'exercise_agent'])
  })

  it('merges names from the completion event without replacing live names', () => {
    expect(
      appendAgentNames(['diet_agent'], ['diet_agent', 'exercise_agent']),
    ).toEqual(['diet_agent', 'exercise_agent'])
  })
})
