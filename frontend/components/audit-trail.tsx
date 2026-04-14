"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollText, FileEdit, MessageSquare, Bell, Plus } from "lucide-react"
import type { AuditEntry } from "@/lib/types"

interface AuditTrailProps {
  entries: AuditEntry[]
}

export function AuditTrail({ entries }: AuditTrailProps) {
  const getActionIcon = (action: string) => {
    if (action.includes("Updated")) return <FileEdit className="h-4 w-4 text-blue-500" />
    if (action.includes("Query")) return <MessageSquare className="h-4 w-4 text-green-500" />
    if (action.includes("Alert")) return <Bell className="h-4 w-4 text-amber-500" />
    if (action.includes("Added")) return <Plus className="h-4 w-4 text-emerald-500" />
    return <ScrollText className="h-4 w-4 text-muted-foreground" />
  }

  const getActionBadge = (action: string) => {
    if (action.includes("Updated")) return "bg-blue-100 text-blue-800"
    if (action.includes("Query")) return "bg-green-100 text-green-800"
    if (action.includes("Alert")) return "bg-amber-100 text-amber-800"
    if (action.includes("Added")) return "bg-emerald-100 text-emerald-800"
    return "bg-gray-100 text-gray-800"
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ScrollText className="h-5 w-5" />
          <CardTitle>Version Control & Audit Trail</CardTitle>
        </div>
        <CardDescription>
          Historical tracking of regulation changes and decision documentation
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-[19px] top-0 bottom-0 w-px bg-border" />

          <div className="space-y-6">
            {entries.map((entry, index) => (
              <div key={entry.id} className="relative flex gap-4">
                {/* Timeline dot */}
                <div className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background border-2 border-border">
                  {getActionIcon(entry.action)}
                </div>

                <div className="flex-1 pb-2">
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge className={getActionBadge(entry.action)}>
                          {entry.action}
                        </Badge>
                        {entry.previousVersion !== entry.newVersion && (
                          <span className="text-xs text-muted-foreground">
                            v{entry.previousVersion} → v{entry.newVersion}
                          </span>
                        )}
                      </div>
                      <h4 className="font-medium text-sm mt-1">{entry.regulationTitle}</h4>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleString()}
                    </span>
                  </div>
                  
                  <p className="text-sm text-muted-foreground">{entry.details}</p>
                  
                  <p className="text-xs text-muted-foreground mt-1">
                    By: {entry.user}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {entries.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            <ScrollText className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No audit entries recorded</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
