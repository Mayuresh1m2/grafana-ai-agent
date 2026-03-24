import { config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach } from 'vitest'

// Install a fresh Pinia before every test
beforeEach(() => {
  setActivePinia(createPinia())
})

// Suppress Vue warnings in tests
config.global.config.warnHandler = () => null
