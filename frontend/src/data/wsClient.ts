/**
 * wsClient — STUB for a future live bridge to the harness over WebSocket.
 * A thin FastAPI server wrapping ColonyHarness.run_round would stream the same
 * ColonyEvent envelopes used by jsonlReplay; this source would parse frames and
 * forward them through the same EventSink. Not wired in the vertical slice.
 */

import type { SimSource, EventSink } from './adapter'
import type { ColonyEvent } from './schema'

export class WsClient implements SimSource {
  readonly id = 'ws' as const
  private sink: EventSink | null = null
  private socket: WebSocket | null = null
  private queue: ColonyEvent[] = []

  constructor(private url: string) {}

  start(sink: EventSink) {
    this.sink = sink
    this.socket = new WebSocket(this.url)
    this.socket.onmessage = (e) => {
      try {
        this.queue.push(JSON.parse(e.data) as ColonyEvent)
      } catch {
        /* ignore */
      }
    }
  }

  update(_dt: number) {
    void _dt
    if (!this.sink) return
    // drain queue → sink (mapping identical to jsonlReplay.emit). Left for the
    // live-bridge milestone; intentionally a no-op in the slice.
    this.queue.length = 0
  }

  stop() {
    this.socket?.close()
    this.socket = null
    this.sink = null
  }
}
