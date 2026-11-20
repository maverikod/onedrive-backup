// useCommand: load the result of one adapter command for a page, optionally poll it, never show demo data.

import { onBeforeUnmount, ref, watch } from 'vue'
import { startPolling, type Poller } from './lib'
import { Aborted, AuthRequired, NetworkError, RateLimited, RpcError, auth } from './rpc'

export interface Banner {
  code: number | string
  message: string
}

export interface PollOptions {
  intervalMs: number
  /** True to keep polling after an answer (the data, or null with the banner of a command error). */
  keepGoing: (data: unknown, banner: Banner | null) => boolean
}

export function useCommand(load: () => Promise<unknown>, poll?: PollOptions) {
  const data = ref<unknown>(null)
  const banner = ref<Banner | null>(null)
  const settled = ref(false)
  const stale = ref(false)
  const lastGood = ref('')
  let poller: Poller | null = null
  let alive = true
  let generation = 0

  function stopPoll(): void {
    if (poller !== null) poller.stop()
    poller = null
  }

  /** One load. False when the page went away or a newer load replaced this one; failures other than a command error are rethrown. */
  async function run(): Promise<boolean> {
    const mine = generation
    try {
      const result = await load()
      if (!alive || mine !== generation) return false
      data.value = result
      banner.value = null
      stale.value = false
      lastGood.value = new Date().toISOString()
    } catch (exc) {
      if (!alive || mine !== generation || exc instanceof Aborted) return false
      if (exc instanceof RpcError) {
        data.value = null
        banner.value = { code: exc.code, message: exc.message }
      } else {
        if (exc instanceof RateLimited || exc instanceof NetworkError) {
          stale.value = true
          if (exc instanceof NetworkError && data.value === null) banner.value = { code: 'NETWORK', message: exc.message }
        }
        throw exc
      }
    } finally {
      if (alive && mine === generation) settled.value = true
    }
    return true
  }

  function restart(): void {
    stopPoll()
    generation += 1
    settled.value = false
    const options = poll
    void run().then(
      (done) => {
        if (done && options && alive && options.keepGoing(data.value, banner.value)) {
          poller = startPolling(async () => (await run()) && options.keepGoing(data.value, banner.value), options.intervalMs)
        }
      },
      (exc) => {
        // A failed first load: a network failure still polls with backoff, a key request waits for the key.
        if (!(exc instanceof AuthRequired) && options && alive) {
          poller = startPolling(async () => (await run()) && options.keepGoing(data.value, banner.value), options.intervalMs)
        }
      },
    )
  }

  watch(() => auth.epoch, restart, { immediate: true })
  onBeforeUnmount(() => {
    alive = false
    stopPoll()
  })

  return { data, banner, settled, stale, lastGood, reload: restart }
}
