import http from './http'

export const uploadImage = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return http
    .post<{ image_url: string }>('/uploads', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data.image_url)
}
