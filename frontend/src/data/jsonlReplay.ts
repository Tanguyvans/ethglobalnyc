/**
 * jsonlReplay — replays a harness JSONL file (public/data/demo.jsonl) as a
 * BUFFERED, TIMED stream of domain events. Events are never applied instantly:
 * they're queued and released at a controlled rate, and they only modulate the
 * running simulation (pulses, flows, stat binding) — they never teleport ants.
 *
 * Wire format mirrors colony_harness/harness.py:write_jsonl plus the
 * `agent_record` roster export. See data/schema.ts.
 */

import type { SimSource, EventSink } from './adapter'
import type { ColonyEvent, AgentRecord } from './schema'
import { sim, type SideCode } from '../store/simStore'

const EVENTS_PER_SEC = 12

/** small stable string hash (FNV-1a-ish) for deterministic per-agent variety. */
function hashId(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export class JsonlReplay implements SimSource {
  readonly id = 'replay' as const
  private sink: EventSink | null = null
  private stream: ColonyEvent[] = []
  private roster: AgentRecord[] = []
  private cursor = 0
  private acc = 0
  private loaded = false

  /** Fetch + parse the JSONL file. Returns false if missing/empty. */
  async load(url = '/data/demo.jsonl'): Promise<boolean> {
    try {
      const res = await fetch(url)
      if (!res.ok) return false
      const text = await res.text()
      const events: ColonyEvent[] = []
      for (const line of text.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed) continue
        try {
          events.push(JSON.parse(trimmed) as ColonyEvent)
        } catch {
          /* skip malformed line */
        }
      }
      if (events.length === 0) return false
      // Roster for up-front binding (so agent_id -> index exists before any
      // claim/forecast references an agent). The harness now emits these
      // roster-first; we also keep them in the stream so multi-round files that
      // re-emit agent_record update evolving bankroll/accuracy/generation.
      this.roster = events.filter((e) => e.event_type === 'agent_record') as AgentRecord[]
      // Replay in original file order (faithful, and correct across rounds);
      // round_summary is applied as it passes.
      this.stream = events
      this.loaded = true
      return true
    } catch {
      return false
    }
  }

  start(sink: EventSink) {
    this.sink = sink
    this.cursor = 0
    this.acc = 0
    // Bind real per-agent stats up front so AntCards show true values.
    for (const rec of this.roster) sink.bindAgent(rec)
  }

  update(dt: number) {
    if (!this.sink || !this.loaded || this.stream.length === 0) return
    this.acc += EVENTS_PER_SEC * dt
    while (this.acc >= 1) {
      this.acc -= 1
      this.emit(this.stream[this.cursor])
      this.cursor++
      if (this.cursor >= this.stream.length) this.cursor = 0 // loop the round
    }
  }

  private emit(ev: ColonyEvent) {
    const sink = this.sink!
    switch (ev.event_type) {
      case 'agent_record': {
        // re-bind on pass-through so evolving stats (multi-round) are reflected
        sink.bindAgent(ev)
        break
      }
      case 'debate_claim': {
        const idx = sim.idToIndex.get(ev.speaker_id)
        if (idx !== undefined) sink.comm(idx, -1, ev.stated_home_probability)
        break
      }
      case 'forecast': {
        const idx = sim.idToIndex.get(ev.agent_id)
        if (idx === undefined || ev.side === 'pass') break
        const side: SideCode = ev.side === 'home' ? 1 : -1
        const amount = Math.min(1, ev.stake / 12)
        // NOTE: the harness only emits non-pass forecasts (edge >= threshold),
        // so `edge > 0` would mark every stake a win. Until there's a real
        // match outcome, derive an ILLUSTRATIVE win/loss that varies per agent
        // (deterministic hash) and leans on edge — so flows show both outcomes.
        const win = (hashId(ev.agent_id) % 1000) / 1000 < 0.5 + ev.edge
        sink.stake(idx, side, amount, win)
        break
      }
      case 'round_summary': {
        sink.updateColony({ growthRate: Math.min(1, ev.total_staked / 200) })
        break
      }
      default:
        break
    }
  }

  stop() {
    this.sink = null
  }
}
