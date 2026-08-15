import { Badge } from "@/components/ui/badge"
import type { JobStatus } from "@/lib/api"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

const STATUS_VARIANTS: Record<JobStatus, BadgeVariant> = {
  queued: "outline",
  running: "secondary",
  succeeded: "default",
  failed: "destructive",
  cancelled: "outline",
}

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <Badge variant={STATUS_VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
}
