import { Clock01Icon, Download01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { STAGE_LABELS, type Job, type JobStatus } from "@/lib/api"
import { downloadResultFile, type ResultNames } from "@/features/ingest/result-file"
import { useCancelJob } from "./use-jobs"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

const STATUS_VARIANTS: Record<JobStatus, BadgeVariant> = {
  queued: "outline",
  running: "secondary",
  succeeded: "default",
  failed: "destructive",
  cancelled: "outline",
}

function isActive(job: Job) {
  return job.status === "queued" || job.status === "running"
}

function JobRow({ job, names }: { job: Job; names?: ResultNames }) {
  const cancelJob = useCancelJob()
  const active = isActive(job)

  return (
    <li className="space-y-3 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="truncate font-medium">{job.title}</p>
          <p className="text-xs text-muted-foreground">
            {job.stage ? STAGE_LABELS[job.stage] : job.status}
            {active && job.progress > 0
              ? ` · ${Math.round(job.progress * 100)}%`
              : null}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={STATUS_VARIANTS[job.status]}>{job.status}</Badge>
          {active ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={cancelJob.isPending}
              onClick={() => cancelJob.mutate(job.jobId)}
            >
              Cancel
            </Button>
          ) : null}
          {job.status === "succeeded" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadResultFile(job, names)}
            >
              <HugeiconsIcon icon={Download01Icon} />
              Download result
            </Button>
          ) : null}
        </div>
      </div>
      {active ? <Progress value={Math.round(job.progress * 100)} /> : null}
      {job.error ? <p className="text-sm text-destructive">{job.error}</p> : null}
    </li>
  )
}

export function JobList({
  jobs,
  resultNames,
}: {
  jobs: Job[]
  resultNames: Record<string, ResultNames>
}) {
  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-12 text-center">
        <HugeiconsIcon icon={Clock01Icon} className="size-5 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No jobs yet. Start one above.
        </p>
      </div>
    )
  }

  return (
    <ul className="divide-y">
      {jobs.map((job) => (
        <JobRow key={job.jobId} job={job} names={resultNames[job.jobId]} />
      ))}
    </ul>
  )
}
