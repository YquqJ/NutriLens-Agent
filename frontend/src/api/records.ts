import http from './http'
import { todayISO } from '@/utils/date'
import type { DietRecord, ExerciseRecord } from '@/types'

const d = () => todayISO()

export const listDietRecords = (date?: string) =>
  http.get<DietRecord[]>('/diet/records', { params: { date: date ?? d() } }).then((r) => r.data)

export const deleteDietRecord = (id: number) => http.delete(`/diet/records/${id}`)

export const updateDietRecord = (id: number, items: { id: number; grams: number }[]) =>
  http.put<DietRecord>(`/diet/records/${id}`, { items }).then((r) => r.data)

export const listExerciseRecords = (date?: string) =>
  http
    .get<ExerciseRecord[]>('/exercise/records', { params: { date: date ?? d() } })
    .then((r) => r.data)

export const deleteExerciseRecord = (id: number) => http.delete(`/exercise/records/${id}`)

export const updateExerciseRecord = (id: number, durationMinutes: number) =>
  http
    .put<ExerciseRecord>(`/exercise/records/${id}`, { duration_minutes: durationMinutes })
    .then((r) => r.data)
