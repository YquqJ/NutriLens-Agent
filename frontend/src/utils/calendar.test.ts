import { describe, expect, it } from 'vitest'
import type { DailySummary, DietRecord, ExerciseRecord } from '@/types'
import { buildMonthGrid, deriveCalendarDayState } from './calendar'

const withinTarget: DailySummary = {
  date: '2026-09-17',
  intake: 1476,
  burned: 286,
  net: 1190,
  calorie_target: 1714,
  remaining: 524,
  macros: { protein: 86, fat: 43, carbs: 168 },
}

describe('calendar utilities', () => {
  it('builds a Monday-first grid with adjacent month padding', () => {
    const grid = buildMonthGrid(2026, 9)

    expect(grid).toHaveLength(35)
    expect(grid[0]).toBe('2026-08-31')
    expect(grid[16]).toBe('2026-09-16')
    expect(grid[17]).toBe('2026-09-17')
  })

  it('marks a day over target while retaining diet and exercise markers', () => {
    const state = deriveCalendarDayState(
      '2026-09-17',
      { ...withinTarget, intake: 1900, remaining: -186 },
      [{ id: 1 } as DietRecord],
      [{ id: 2 } as ExerciseRecord],
    )

    expect(state.status).toBe('over_target')
    expect(state.hasDiet).toBe(true)
    expect(state.hasExercise).toBe(true)
  })

  it('marks a day with no records separately from a day without calorie target', () => {
    const noRecords = deriveCalendarDayState('2026-09-18', withinTarget, [], [])
    const noTarget = deriveCalendarDayState(
      '2026-09-19',
      { ...withinTarget, calorie_target: null, remaining: null },
      [{ id: 1 } as DietRecord],
      [],
    )

    expect(noRecords.status).toBe('no_records')
    expect(noTarget.status).toBe('no_target')
  })
})
