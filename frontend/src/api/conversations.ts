import http from './http'
import type { Conversation, MessagePage } from '@/types'

export const MESSAGE_PAGE_SIZE = 30

export const listConversations = () =>
  http.get<Conversation[]>('/conversations').then((r) => r.data)

export const createConversation = (title = '新会话') =>
  http.post<Conversation>('/conversations', { title }).then((r) => r.data)

export const getMessages = (id: string, pageNo = 1, pageSize = MESSAGE_PAGE_SIZE) =>
  http
    .get<MessagePage>(`/conversations/${id}/messages`, { params: { pageNo, pageSize } })
    .then((r) => r.data)

export const deleteConversation = (id: string) => http.delete(`/conversations/${id}`)
