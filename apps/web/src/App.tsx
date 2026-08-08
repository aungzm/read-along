import { AppShell } from "@/app/app-shell"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function App() {
  return (
    <AppShell>
      <Card>
        <CardHeader>
          <CardTitle>No jobs yet</CardTitle>
          <CardDescription>
            Upload an EPUB and its audiobook to start an alignment job.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          The job list will appear here once the API is connected.
        </CardContent>
      </Card>
    </AppShell>
  )
}

export default App
