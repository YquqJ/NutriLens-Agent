import http from './http'
import type { Conversation, Message } from '@/types'

export const listConversations = () =>
  http.get<Conversation[]>('/conversations').then((r) => r.data)

export const createConversation = (title = '新会话') =>
  http.post<Conversation>('/conversations', { title }).then((r) => r.data)

export const getMessages = (id: string) =>
  http.get<Message[]>(`/conversations/${id}/messages`).then((r) => r.data)

export const deleteConversation = (id: string) => http.delete(`/conversations/${id}`)
