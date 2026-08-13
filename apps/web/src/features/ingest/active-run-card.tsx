import {
  CheckmarkCircle02Icon,
  Loading03Icon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { STAGES, STAGE_LABELS, type Job } from "@/lib/api"
import { useCancelJob } from "@/features/jobs/use-jobs"

function StageStep({
  label,
  state,
}: {
  label: string
  state: "done" | "active" | "pending"
}) {
  return (
    <li className="flex items-center gap-2 text-sm">
      {state === "done" ? (
        <HugeiconsIcon
          icon={CheckmarkCircle02Icon}
          className="size-4 text-primary"
        />
      ) : state === "active" ? (
        <HugeiconsIcon
          icon={Loading03Icon}
          className="size-4 animate-spin text-primary"
        />
      ) : (
        <span className="size-4 rounded-full border border-muted-foreground/40" />
      )}
      <span
        className={
          state === "pending" ? "text-muted-foreground" : "font-medium"
        }
      >
        {label}
      </span>
    </li>
  )
}

/**
 * The live run card. Follows the active job's server-sent events (already
 * folded into the query cache) and renders the stage pipeline plus the
 * overall progress bar. Mock stages advance on the backend timer.
 */
export function ActiveRunCard({ job }: { job: Job }) {
  const cancelJob = useCancelJob()
  const percent = Math.round(job.progress * 100)
  const activeIndex = job.stage ? STAGES.indexOf(job.stage) : -1

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">
              {job.status === "queued" ? "Queued" : "Aligning"} · {job.title}
            </CardTitle>
            <CardDescription>
              Mock run — stages advance on a timer. Nothing is really aligned
              yet.
            </CardDescription>
          </div>
          <Badge variant="secondary">{job.status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="grid gap-2 sm:grid-cols-2">
          {STAGES.map((stage, index) => (
            <StageStep
              key={stage}
              label={STAGE_LABELS[stage]}
              state={
                job.status === "queued" || index > activeIndex
                  ? "pending"
                  : index === activeIndex
                    ? "active"
                    : "done"
              }
            />
          ))}
        </ol>
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
      </CardContent>
    </Card>
  )
}
