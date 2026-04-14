"use client"

import { Card, CardContent } from "@/components/ui/card"
import { BookOpen, Bell, MessageCircle, Clock } from "lucide-react"

interface DashboardStatsProps {
  totalRegulations: number
  pendingAlerts: number
  queriesThisMonth: number
  lastSyncTime: string
}

export function DashboardStats({
  totalRegulations,
  pendingAlerts,
  queriesThisMonth,
  lastSyncTime,
}: DashboardStatsProps) {
  const stats = [
    {
      label: "Active Regulations",
      value: totalRegulations,
      icon: BookOpen,
      color: "text-blue-600",
      bgColor: "bg-blue-100",
    },
    {
      label: "Pending Alerts",
      value: pendingAlerts,
      icon: Bell,
      color: "text-amber-600",
      bgColor: "bg-amber-100",
    },
    {
      label: "Queries This Month",
      value: queriesThisMonth,
      icon: MessageCircle,
      color: "text-green-600",
      bgColor: "bg-green-100",
    },
    {
      label: "Last HCD Sync",
      value: lastSyncTime,
      icon: Clock,
      color: "text-gray-600",
      bgColor: "bg-gray-100",
      isText: true,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <Card key={stat.label}>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${stat.bgColor}`}>
                <stat.icon className={`h-5 w-5 ${stat.color}`} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
                <p className={`font-semibold ${stat.isText ? "text-sm" : "text-xl"}`}>
                  {stat.value}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
