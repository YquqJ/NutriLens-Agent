import type { DailySummary, DietRecord, ExerciseRecord } from '@/types'

export type CalendarDayStatus = 'within_target' | 'over_target' | 'no_records' | 'no_target'

export interface CalendarDayState {
  date: string
  day: number
  inMonth: boolean
  hasDiet: boolean
  hasExercise: boolean
  status: CalendarDayStatus
  intake: number
}

function toISODate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function buildMonthGrid(year: number, month: number): string[] {
  const firstDay = new Date(year, month - 1, 1)
  const mondayOffset = (firstDay.getDay() + 6) % 7
  const daysInMonth = new Date(year, month, 0).getDate()
  const cells = Math.ceil((mondayOffset + daysInMonth) / 7) * 7
  const start = new Date(year, month - 1, 1 - mondayOffset)

  return Array.from({ length: cells }, (_, index) => {
    const value = new Date(start)
    value.setDate(start.getDate() + index)
    return toISODate(value)
  })
}

export function deriveCalendarDayState(
  date: string,
  summary: DailySummary | null,
  dietRecords: DietRecord[],
  exerciseRecords: ExerciseRecord[],
): CalendarDayState {
  const hasDiet = dietRecords.length > 0
  const hasExercise = exerciseRecords.length > 0
  const hasRecords = hasDiet || hasExercise
  const target = summary?.calorie_target ?? null

  let status: CalendarDayStatus = 'within_target'
  if (!hasRecords) status = 'no_records'
  else if (target == null) status = 'no_target'
  else if ((summary?.remaining ?? 0) < 0) status = 'over_target'

  const [, , day] = date.split('-')
  return {
    date,
    day: Number(day),
    inMonth: true,
    hasDiet,
    hasExercise,
    status,
    intake: summary?.intake ?? 0,
  }
}
