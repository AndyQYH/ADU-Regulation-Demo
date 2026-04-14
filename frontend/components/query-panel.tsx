"use client"

import { useState } from "react"
import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Search, MessageCircle, Clock, FileText, Bot, User, Sparkles, ChevronDown } from "lucide-react"
import type { Query } from "@/lib/types"

interface QueryPanelProps {
  recentQueries: Query[]
  onNewQuery: (query: Query) => void
}

const sampleQuestions = [
  "What types of design standards can a city or HOA impose on an ADU without violating state law?",
  "What are the minimum side and rear yard setback requirements for a detached ADU, and can a city require more?",
  "When can a city charge impact fees for an ADU, and how must those fees be calculated?",
]

function getTextFromParts(parts?: Array<{ type: string; text?: string }>): string {
  if (!parts || !Array.isArray(parts)) return ""
  return parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("")
}

function extractSourceTrace(text: string): {
  cleanedText: string
  primarySource: string | null
  appliedUpdates: string | null
  rationale: string | null
  actionableGuidance: string | null
} {
  const lines = text.split("\n")
  const stripBulletPrefix = (value: string) => value.replace(/^[-*]\s*/, "")
  const normalize = (value: string) => stripBulletPrefix(value.trim())

  let primarySource: string | null = null
  let appliedUpdates: string | null = null
  let rationale: string | null = null
  let actionableGuidance: string | null = null

  let shortAnswerHeadingIndex = -1
  let rationaleHeadingIndex = -1
  let guidanceHeadingIndex = -1
  const metadataLineIndexes = new Set<number>()

  for (let index = 0; index < lines.length; index += 1) {
    const normalized = normalize(lines[index])
    const lower = normalized.toLowerCase()
    if (lower.startsWith("short answer")) {
      if (shortAnswerHeadingIndex < 0) shortAnswerHeadingIndex = index
      continue
    }
    if (lower.startsWith("short reasoning") || lower.startsWith("why") || lower.startsWith("reason")) {
      if (rationaleHeadingIndex < 0) rationaleHeadingIndex = index
      continue
    }
    if (lower.startsWith("what to do next") || lower.startsWith("actionable guidance")) {
      if (guidanceHeadingIndex < 0) guidanceHeadingIndex = index
      continue
    }
    if (lower.startsWith("primary source:")) {
      primarySource = normalized.slice("primary source:".length).trim() || null
      metadataLineIndexes.add(index)
      continue
    }
    if (lower.startsWith("applied updates:")) {
      appliedUpdates = normalized.slice("applied updates:".length).trim() || null
      metadataLineIndexes.add(index)
      continue
    }
  }

  const collectSection = (startIndex: number, endIndex: number) => {
    if (startIndex < 0) return null

    const heading = normalize(lines[startIndex])
    const headingInline = heading.includes(":") ? heading.split(":").slice(1).join(":").trim() : ""

    const section = lines
      .slice(startIndex + 1, endIndex > startIndex ? endIndex : undefined)
      .filter((line) => {
        const value = normalize(line).toLowerCase()
        return !value.startsWith("primary source:") && !value.startsWith("applied updates:")
      })
      .join("\n")
      .trim()
    const withInline = [headingInline, section].filter(Boolean).join("\n").trim()
    return withInline || null
  }

  const rationaleStart = rationaleHeadingIndex
  const rationaleEnd = guidanceHeadingIndex > rationaleStart ? guidanceHeadingIndex : lines.length
  if (rationaleStart >= 0) {
    rationale = collectSection(rationaleStart, rationaleEnd)
  }

  if (guidanceHeadingIndex >= 0) {
    actionableGuidance = collectSection(guidanceHeadingIndex, lines.length)
  }

  const shortAnswerEndCandidates = [rationaleHeadingIndex, guidanceHeadingIndex].filter((i) => i > shortAnswerHeadingIndex)
  const shortAnswerEnd = shortAnswerEndCandidates.length > 0 ? Math.min(...shortAnswerEndCandidates) : lines.length
  const shortAnswerBody = shortAnswerHeadingIndex >= 0 ? collectSection(shortAnswerHeadingIndex, shortAnswerEnd) : null

  const excludedIndexes = new Set<number>(metadataLineIndexes)
  if (shortAnswerHeadingIndex >= 0) {
    excludedIndexes.add(shortAnswerHeadingIndex)
  }
  if (rationaleHeadingIndex >= 0) {
    for (let i = rationaleHeadingIndex; i < (guidanceHeadingIndex > rationaleHeadingIndex ? guidanceHeadingIndex : lines.length); i += 1) {
      excludedIndexes.add(i)
    }
  }
  if (guidanceHeadingIndex >= 0) {
    for (let i = guidanceHeadingIndex; i < lines.length; i += 1) {
      excludedIndexes.add(i)
    }
  }

  const fallbackBody = lines
    .filter((_, index) => !excludedIndexes.has(index))
    .join("\n")
    .trim()

  return {
    cleanedText: (shortAnswerBody || fallbackBody).trim(),
    primarySource,
    appliedUpdates,
    rationale,
    actionableGuidance,
  }
}

export function QueryPanel({ recentQueries, onNewQuery }: QueryPanelProps) {
  const [input, setInput] = useState("")
  const [useLiveUpdates, setUseLiveUpdates] = useState(false)
  const chatApiUrl = process.env.NEXT_PUBLIC_CHAT_API_URL ?? "/api/chat"
  const liveSearchUrl = process.env.NEXT_PUBLIC_REGULATIONS_SEARCH_URL
  const liveMaxBills = Number(process.env.NEXT_PUBLIC_REGULATIONS_MAX_BILLS ?? "") || undefined
  
  const { messages, sendMessage, status } = useChat({
    transport: new DefaultChatTransport({ api: chatApiUrl }),
    onFinish: ({ message, messages: finishedMessages }) => {
      const text = getTextFromParts(message.parts)
      if (message.role === "assistant" && text) {
        const versionMatch = text.match(/v(\d+\.\d+)/i)
        const lastUserMessage = [...finishedMessages].reverse().find((m) => m.role === "user")
        const newQuery: Query = {
          id: message.id,
          question: lastUserMessage ? getTextFromParts(lastUserMessage.parts) : "Query",
          answer: text,
          regulationVersion: versionMatch ? versionMatch[1] : "4.0",
          timestamp: new Date().toISOString(),
          category: detectCategory(text)
        }
        onNewQuery(newQuery)
      }
    }
  })

  const isLoading = status === "streaming" || status === "submitted"

  const detectCategory = (text: string): string => {
    const lower = text.toLowerCase()
    if (lower.includes("height") || lower.includes("story") || lower.includes("feet")) return "height"
    if (lower.includes("setback") || lower.includes("property line")) return "setback"
    if (lower.includes("floor area") || lower.includes("square feet") || lower.includes("sq ft")) return "general"
    if (lower.includes("design") || lower.includes("architectural")) return "design"
    return "general"
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    const data: Record<string, unknown> = { use_live_updates: useLiveUpdates }
    if (useLiveUpdates && liveSearchUrl) data.search_url = liveSearchUrl
    if (useLiveUpdates && liveMaxBills) data.max_bills = liveMaxBills
    sendMessage({ text: input, metadata: data })
    setInput("")
  }

  const handleQuickQuestion = (q: string) => {
    if (isLoading) return
    const data: Record<string, unknown> = { use_live_updates: useLiveUpdates }
    if (useLiveUpdates && liveSearchUrl) data.search_url = liveSearchUrl
    if (useLiveUpdates && liveMaxBills) data.max_bills = liveMaxBills
    sendMessage({ text: q, metadata: data })
  }

  const getCategoryColor = (category: string) => {
    switch (category) {
      case "height": return "bg-blue-100 text-blue-800"
      case "setback": return "bg-green-100 text-green-800"
      case "design": return "bg-amber-100 text-amber-800"
      default: return "bg-gray-100 text-gray-800"
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            AI-Powered ADU Assistant
          </CardTitle>
          <CardDescription>
            Ask questions about California ADU regulations. Powered by AI with real-time streaming responses.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <Input
              placeholder="Ask about ADU regulations..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              className="flex-1"
              disabled={isLoading}
            />
            <Button type="submit" disabled={isLoading || !input.trim()}>
              <Search className="h-4 w-4 mr-2" />
              {isLoading ? "Thinking..." : "Ask"}
            </Button>
          </form>

          <div className="flex flex-wrap gap-2">
            <span className="text-sm text-muted-foreground">Quick questions:</span>
            {sampleQuestions.map((q) => (
              <Button
                key={q}
                variant="outline"
                size="sm"
                onClick={() => handleQuickQuestion(q)}
                className="text-xs"
                disabled={isLoading}
              >
                {q}
              </Button>
            ))}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/30 px-3 py-2">
            <div className="space-y-1">
              <Label className="text-sm">Answer context</Label>
              <p className="text-xs text-muted-foreground">
                {useLiveUpdates
                  ? "Live internet sources (fetch and synthesize)"
                  : "Database snapshots (local context)"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Live</span>
              <Switch
                checked={useLiveUpdates}
                onCheckedChange={setUseLiveUpdates}
                aria-label="Toggle live regulation updates"
              />
            </div>
          </div>

          {/* Chat Messages */}
          {messages.length > 0 && (
            <div className="border rounded-lg divide-y max-h-96 overflow-y-auto">
              {messages.map((message) => {
                const text = getTextFromParts(message.parts)
                if (!text) return null
                const trace = message.role === "assistant" ? extractSourceTrace(text) : null
                const displayText = trace?.cleanedText ?? text
                
                return (
                  <div
                    key={message.id}
                    className={`p-4 ${message.role === "assistant" ? "bg-muted/50" : "bg-background"}`}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`p-2 rounded-full shrink-0 ${
                        message.role === "assistant" 
                          ? "bg-primary text-primary-foreground" 
                          : "bg-muted"
                      }`}>
                        {message.role === "assistant" ? (
                          <Bot className="h-4 w-4" />
                        ) : (
                          <User className="h-4 w-4" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-muted-foreground mb-1">
                          {message.role === "assistant" ? "ADU Assistant" : "You"}
                        </p>
                        <div className="text-sm whitespace-pre-wrap">{displayText}</div>
                        {message.role === "assistant" && trace?.rationale && (
                          <Collapsible className="mt-2 rounded-md border bg-background">
                            <CollapsibleTrigger className="flex w-full items-center justify-between p-2 text-left text-xs font-medium text-muted-foreground">
                              <span>Short Reasoning</span>
                              <ChevronDown className="h-3.5 w-3.5" />
                            </CollapsibleTrigger>
                            <CollapsibleContent className="px-2 pb-2">
                              <div className="text-xs whitespace-pre-wrap text-muted-foreground">
                                {trace.rationale}
                              </div>
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                        {message.role === "assistant" && (trace?.primarySource || trace?.appliedUpdates) && (
                          <Collapsible className="mt-3 rounded-md border bg-background">
                            <CollapsibleTrigger className="flex w-full items-center justify-between p-2 text-left text-xs font-medium text-muted-foreground">
                              <span>Source Traceability</span>
                              <ChevronDown className="h-3.5 w-3.5" />
                            </CollapsibleTrigger>
                            <CollapsibleContent className="px-2 pb-2 space-y-1">
                              {trace?.primarySource && (
                                <p className="text-xs text-muted-foreground">
                                  <span className="font-medium">Primary source:</span> {trace.primarySource}
                                </p>
                              )}
                              {trace?.appliedUpdates && (
                                <p className="text-xs text-muted-foreground">
                                  <span className="font-medium">Applied updates:</span> {trace.appliedUpdates}
                                </p>
                              )}
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                        {message.role === "assistant" && trace?.actionableGuidance && (
                          <Collapsible className="mt-2 rounded-md border bg-background">
                            <CollapsibleTrigger className="flex w-full items-center justify-between p-2 text-left text-xs font-medium text-muted-foreground">
                              <span>Actionable Guidance</span>
                              <ChevronDown className="h-3.5 w-3.5" />
                            </CollapsibleTrigger>
                            <CollapsibleContent className="px-2 pb-2">
                              <div className="text-xs whitespace-pre-wrap text-muted-foreground">
                                {trace.actionableGuidance}
                              </div>
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                        {message.role === "assistant" && (
                          <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                            <FileText className="h-3 w-3" />
                            <span>Based on current CA ADU regulations</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
              
              {isLoading && messages[messages.length - 1]?.role === "user" && (
                <div className="p-4 bg-muted/50">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-full bg-primary text-primary-foreground shrink-0">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div className="flex-1">
                      <p className="text-xs font-medium text-muted-foreground mb-1">ADU Assistant</p>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <div className="flex gap-1">
                          <span className="animate-bounce">.</span>
                          <span className="animate-bounce" style={{ animationDelay: "0.1s" }}>.</span>
                          <span className="animate-bounce" style={{ animationDelay: "0.2s" }}>.</span>
                        </div>
                        <span>Analyzing regulations</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {messages.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              <MessageCircle className="h-12 w-12 mx-auto mb-3 opacity-50" />
              <p className="text-sm">Ask a question to get started</p>
              <p className="text-xs mt-1">The AI assistant knows California ADU regulations</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Queries</CardTitle>
        </CardHeader>
        <CardContent>
          {recentQueries.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No queries yet. Ask a question above!
            </p>
          ) : (
            <div className="space-y-3">
              {recentQueries.slice(0, 5).map((query) => (
                <div
                  key={query.id}
                  className="p-3 border rounded-lg hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium line-clamp-1">{query.question}</p>
                    <Badge className={getCategoryColor(query.category)}>
                      {query.category}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {query.answer}
                  </p>
                  <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      v{query.regulationVersion}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(query.timestamp).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
