import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')

  async function login(user: string, password: string) {
    const res = await api.post('/api/auth/login', { username: user, password })
    token.value = res.data.access_token
    username.value = res.data.username
    localStorage.setItem('token', token.value)
    localStorage.setItem('username', username.value)
  }

  function logout() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
  }

  return { token, username, login, logout }
})
