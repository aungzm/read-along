import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { STAGES, STAGE_LABELS, type Job } from "@/lib/api"
import { useCancelJob } from "@/features/jobs/use-jobs"
import { JobStatusBadge } from "@/features/jobs/status-badge"

type StepState = "done" | "active" | "pending"

/** A filled dot per stage, strung along a rule: the alignment as a tape. */
function StageTape({ stateFor }: { stateFor: (index: number) => StepState }) {
  return (
    <ol className="relative flex flex-col gap-3 sm:grid sm:grid-cols-5 sm:gap-1">
      <span
        aria-hidden="true"
        className="absolute inset-x-1.5 top-[0.4rem] hidden h-px bg-border sm:block"
      />
      {STAGES.map((stage, index) => {
        const state = stateFor(index)
        return (
          <li
            key={stage}
            className="relative flex items-center gap-3 sm:flex-col sm:items-center sm:gap-2 sm:text-center"
          >
            <span
              aria-hidden="true"
              className={
                state === "pending"
                  ? "size-3.5 shrink-0 rounded-full border border-border bg-background"
                  : state === "active"
                    ? "stage-live size-3.5 shrink-0 rounded-full bg-voice ring-2 ring-voice/25"
                    : "size-3.5 shrink-0 rounded-full bg-voice"
              }
            />
            <span
              className={
                state === "pending"
                  ? "text-xs leading-tight text-muted-foreground sm:text-[0.7rem]"
                  : "text-xs leading-tight font-medium sm:text-[0.7rem]"
              }
            >
              {STAGE_LABELS[stage]}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * The live run strip. Follows the active job's server-sent events (already
 * folded into the query cache) and renders the stage tape plus the overall
 * progress. Mock stages advance on the backend timer.
 */
export function ActiveRunCard({ job }: { job: Job }) {
  const cancelJob = useCancelJob()
  const percent = Math.round(job.progress * 100)
  const activeIndex = job.stage ? STAGES.indexOf(job.stage) : -1

  const stateFor = (index: number): StepState => {
    if (job.status === "queued" || index > activeIndex) return "pending"
    return index === activeIndex ? "active" : "done"
  }

  return (
    <article className="overflow-hidden rounded-xl border border-border/70">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 bg-paper/50 px-5 py-4">
        <div className="space-y-1">
          <h3 className="font-reading text-base font-medium">{job.title}</h3>
          <p className="text-xs text-muted-foreground">
            {job.status === "queued" ? "Waiting to start" : "Aligning"}. Stages
            advance on a timer; nothing is really aligned yet.
          </p>
        </div>
        <JobStatusBadge status={job.status} />
      </header>

      <div className="space-y-5 px-5 py-5">
        <StageTape stateFor={stateFor} />

        <div className="space-y-2">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-muted-foreground">
              {job.stage ? STAGE_LABELS[job.stage] : "Waiting to start"}
            </span>
            <span className="font-medium tabular-nums">{percent}%</span>
          </div>
          <Progress value={percent} />
        </div>

        <Button
          variant="outline"
          size="sm"
          disabled={cancelJob.isPending}
          onClick={() => cancelJob.mutate(job.jobId)}
        >
          Cancel run
        </Button>
      </div>
    </article>
  )
}
