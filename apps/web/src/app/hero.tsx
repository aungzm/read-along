/**
 * The page hero: one sentence of prose with its currently-narrated phrase lit
 * up, above a waveform. This is the product in a single image — text and
 * narration locked together — rather than a heading over a card.
 */

const BAR_COUNT = 64
const VIEW_HEIGHT = 48

/** A fixed, gently tapered waveform. Deterministic so it never flickers. */
const BARS = Array.from({ length: BAR_COUNT }, (_, index) => {
  const noise = Math.abs(Math.sin(index * 12.9898) * 43758.5453) % 1
  const envelope = 0.5 + 0.5 * Math.sin((index / (BAR_COUNT - 1)) * Math.PI)
  return 5 + noise * 38 * envelope
})

function Waveform() {
  return (
    <svg
      viewBox={`0 0 ${BAR_COUNT * 4} ${VIEW_HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      className="h-10 w-full"
    >
      <defs>
        <linearGradient id="voice-ramp" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--voice)" />
          <stop offset="100%" stopColor="var(--voice-bright)" />
        </linearGradient>
      </defs>
      <g className="text-foreground/15" fill="currentColor">
        {BARS.map((height, index) => (
          <rect
            key={index}
            x={index * 4}
            y={(VIEW_HEIGHT - height) / 2}
            width="2"
            height={height}
            rx="1"
          />
        ))}
      </g>
      <g className="wave-play" fill="url(#voice-ramp)">
        {BARS.map((height, index) => (
          <rect
            key={index}
            x={index * 4}
            y={(VIEW_HEIGHT - height) / 2}
            width="2"
            height={height}
            rx="1"
          />
        ))}
      </g>
    </svg>
  )
}

export function Hero() {
  return (
    <section className="space-y-6">
      <h1 className="max-w-[24ch] font-reading text-3xl leading-tight font-medium tracking-tight text-balance sm:text-4xl">
        Every word, kept in time with the narration.
      </h1>

      <figure className="rounded-xl border border-border/70 bg-paper/50 px-6 py-6 sm:px-8 sm:py-7">
        <blockquote className="font-reading text-lg leading-relaxed text-pretty sm:text-xl">
          The river ran quietly past the willows, and{" "}
          <span className="spoken">
            <span className="spoken-wash" aria-hidden="true" />
            <span className="spoken-text">every word kept time</span>
          </span>
          .
        </blockquote>

        <div className="mt-6 flex items-center gap-4">
          <svg
            viewBox="0 0 12 14"
            aria-hidden="true"
            className="size-3.5 shrink-0 fill-voice"
          >
            <path d="M0 0.5v13l11-6.5z" />
          </svg>
          <Waveform />
        </div>

        <figcaption className="mt-3 flex items-baseline justify-between text-xs text-muted-foreground">
          <span>Narration is playing</span>
          <span className="tabular-nums">00:12</span>
        </figcaption>
      </figure>
    </section>
  )
}
