export const maxDuration = 30

const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

function resolveChatUrl(base: string): string {
  const trimmed = base.replace(/\/$/, "")
  if (trimmed.endsWith("/api/chat")) {
    return trimmed
  }
  return `${trimmed}/api/chat`
}

export async function POST(req: Request) {
  const proxyRequestId = crypto.randomUUID().slice(0, 12)
  const chatUrl = resolveChatUrl(FASTAPI_URL)
  const started = Date.now()
  const payload = await req.json()
  const data = payload?.data ?? payload?.metadata

  if (data && typeof data === "object") {
    if (payload.use_live_updates === undefined && "use_live_updates" in data) {
      payload.use_live_updates = data.use_live_updates
    }
    if (payload.search_url === undefined && "search_url" in data) {
      payload.search_url = data.search_url
    }
    if (payload.max_bills === undefined && "max_bills" in data) {
      payload.max_bills = data.max_bills
    }
  }

  const body = JSON.stringify(payload)

  console.info(`[chat-proxy] start id=${proxyRequestId} upstream=${chatUrl}`)

  const upstream = await fetch(chatUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body,
    signal: req.signal,
  })

  const headers = new Headers()
  const contentType = upstream.headers.get("Content-Type") ?? "text/event-stream"
  headers.set("Content-Type", contentType)
  headers.set("Cache-Control", upstream.headers.get("Cache-Control") ?? "no-cache")
  headers.set("Connection", upstream.headers.get("Connection") ?? "keep-alive")
  headers.set(
    "X-Vercel-AI-UI-Message-Stream",
    upstream.headers.get("X-Vercel-AI-UI-Message-Stream") ?? "v1"
  )
  headers.set(
    "X-Accel-Buffering",
    upstream.headers.get("X-Accel-Buffering") ?? "no"
  )
  const upstreamRequestId = upstream.headers.get("x-request-id")
  if (upstreamRequestId) {
    headers.set("x-request-id", upstreamRequestId)
  }

  console.info(
    `[chat-proxy] end id=${proxyRequestId} status=${upstream.status} duration_ms=${Date.now() - started} upstream_request_id=${upstreamRequestId ?? "n/a"}`
  )

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  })
}
