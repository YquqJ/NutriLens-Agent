import http from './http'
import type { DietRecord, ExerciseRecord } from '@/types'

const d = () => new Date().toISOString().slice(0, 10)

export const listDietRecords = (date?: string) =>
  http.get<DietRecord[]>('/diet/records', { params: { date: date ?? d() } }).then((r) => r.data)

export const deleteDietRecord = (id: number) => http.delete(`/diet/records/${id}`)

export const listExerciseRecords = (date?: string) =>
  http
    .get<ExerciseRecord[]>('/exercise/records', { params: { date: date ?? d() } })
    .then((r) => r.data)

export const deleteExerciseRecord = (id: number) => http.delete(`/exercise/records/${id}`)
